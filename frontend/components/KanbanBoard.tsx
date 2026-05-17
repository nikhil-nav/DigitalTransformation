"use client";

import { useCallback, useEffect, useMemo, useState, type KeyboardEvent } from "react";

import { api, ApiError, type Capability, type CapabilityLevel } from "@/lib/api";

type CapNode = Capability & { children: CapNode[] };

function buildTree(flat: Capability[]): CapNode[] {
  const byId = new Map<number, CapNode>();
  for (const c of flat) byId.set(c.id, { ...c, children: [] });
  const roots: CapNode[] = [];
  for (const c of byId.values()) {
    if (c.parent_id === null) {
      roots.push(c);
    } else {
      const parent = byId.get(c.parent_id);
      if (parent) parent.children.push(c);
    }
  }
  function sortRecursive(nodes: CapNode[]) {
    nodes.sort((a, b) => a.position - b.position);
    for (const n of nodes) sortRecursive(n.children);
  }
  sortRecursive(roots);
  return roots;
}

export default function KanbanBoard({
  projectId,
  refreshKey = 0,
}: {
  projectId: number;
  refreshKey?: number;
}) {
  const [caps, setCaps] = useState<Capability[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [confirmingDelete, setConfirmingDelete] = useState<Capability | null>(
    null,
  );

  const load = useCallback(async () => {
    try {
      const list = await api.listCapabilities(projectId);
      setCaps(list);
      setError(null);
    } catch (e: unknown) {
      setError(
        e instanceof ApiError ? e.message : "Failed to load capabilities",
      );
    }
  }, [projectId]);

  useEffect(() => {
    load();
  }, [load, refreshKey]);

  const tree = useMemo(() => buildTree(caps ?? []), [caps]);

  async function withBusy<T>(fn: () => Promise<T>): Promise<T | null> {
    setBusy(true);
    setError(null);
    try {
      return await fn();
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : "Action failed");
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function handleAdd(
    level: CapabilityLevel,
    parentId: number | null,
    name: string,
  ) {
    const result = await withBusy(() =>
      api.createCapability(projectId, { level, parent_id: parentId, name }),
    );
    if (result) await load();
  }

  async function handleRename(cap: Capability, name: string) {
    if (name === cap.name) return;
    const result = await withBusy(() =>
      api.updateCapability(projectId, cap.id, { name }),
    );
    if (result) await load();
  }

  async function handleEditDescription(cap: Capability, description: string) {
    const next = description.trim() || null;
    if (next === (cap.description ?? null)) return;
    const result = await withBusy(() =>
      api.updateCapability(projectId, cap.id, { description: next }),
    );
    if (result) await load();
  }

  async function handleMove(cap: Capability, delta: -1 | 1) {
    const siblings = (caps ?? [])
      .filter((c) => c.parent_id === cap.parent_id)
      .sort((a, b) => a.position - b.position);
    const idx = siblings.findIndex((s) => s.id === cap.id);
    const target = idx + delta;
    if (target < 0 || target >= siblings.length) return;
    const a = siblings[idx];
    const b = siblings[target];
    const result = await withBusy(async () => {
      await api.updateCapability(projectId, a.id, { position: b.position });
      await api.updateCapability(projectId, b.id, { position: a.position });
      return true;
    });
    if (result) await load();
  }

  async function handleDelete(cap: Capability) {
    const result = await withBusy(() => api.deleteCapability(projectId, cap.id));
    setConfirmingDelete(null);
    if (result !== null) {
      setExpanded((s) => {
        const next = new Set(s);
        next.delete(cap.id);
        return next;
      });
      await load();
    }
  }

  function toggle(id: number) {
    setExpanded((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  if (caps === null && !error) {
    return (
      <section className="card kanban-card">
        <h2>Business Capability Map</h2>
        <div className="status">Loading capabilities...</div>
      </section>
    );
  }

  return (
    <section className="card kanban-card">
      <div className="row-between">
        <h2>Business Capability Map</h2>
        <span className="meta">L1 / L2 / L3</span>
      </div>

      {error && (
        <div role="alert" className="status error">
          {error}
        </div>
      )}

      {tree.length === 0 && (
        <p className="meta">
          No capabilities yet. Add an L1 or chat with the agent (Part C) to get
          started.
        </p>
      )}

      <div className="kanban">
        {tree.map((l1, l1Idx) => (
          <div key={l1.id} className="kanban-col">
            <div className="kanban-col-header">
              <InlineText
                value={l1.name}
                onSave={(v) => handleRename(l1, v)}
                disabled={busy}
                ariaLabel="L1 name"
                className="kanban-col-name"
              />
              <RowActions
                onUp={() => handleMove(l1, -1)}
                onDown={() => handleMove(l1, +1)}
                onDelete={() => setConfirmingDelete(l1)}
                upDisabled={busy || l1Idx === 0}
                downDisabled={busy || l1Idx === tree.length - 1}
                disabled={busy}
                label="L1"
              />
            </div>
            <div className="kanban-cards">
              {l1.children.map((l2, l2Idx) => {
                const isOpen = expanded.has(l2.id);
                return (
                  <div
                    key={l2.id}
                    className={`kanban-card-l2${isOpen ? " expanded" : ""}`}
                  >
                    <div className="kanban-card-row">
                      <button
                        type="button"
                        className="kanban-card-toggle"
                        onClick={() => toggle(l2.id)}
                        aria-label={isOpen ? "Collapse L2" : "Expand L2"}
                      >
                        {isOpen ? "▾" : "▸"}
                      </button>
                      <InlineText
                        value={l2.name}
                        onSave={(v) => handleRename(l2, v)}
                        disabled={busy}
                        ariaLabel="L2 name"
                        className="kanban-card-name"
                      />
                      <RowActions
                        onUp={() => handleMove(l2, -1)}
                        onDown={() => handleMove(l2, +1)}
                        onDelete={() => setConfirmingDelete(l2)}
                        upDisabled={busy || l2Idx === 0}
                        downDisabled={busy || l2Idx === l1.children.length - 1}
                        disabled={busy}
                        label="L2"
                      />
                    </div>
                    {isOpen && (
                      <div className="kanban-card-body">
                        <InlineText
                          value={l2.description ?? ""}
                          onSave={(v) => handleEditDescription(l2, v)}
                          disabled={busy}
                          placeholder="Add description..."
                          multiline
                          ariaLabel="L2 description"
                        />
                        <ul className="l3-list">
                          {l2.children.map((l3, l3Idx) => (
                            <li key={l3.id} className="l3-item">
                              <InlineText
                                value={l3.name}
                                onSave={(v) => handleRename(l3, v)}
                                disabled={busy}
                                ariaLabel="L3 name"
                              />
                              <RowActions
                                onUp={() => handleMove(l3, -1)}
                                onDown={() => handleMove(l3, +1)}
                                onDelete={() => setConfirmingDelete(l3)}
                                upDisabled={busy || l3Idx === 0}
                                downDisabled={
                                  busy || l3Idx === l2.children.length - 1
                                }
                                disabled={busy}
                                label="L3"
                              />
                            </li>
                          ))}
                        </ul>
                        <AddInline
                          level={3}
                          parentId={l2.id}
                          disabled={busy}
                          onAdd={handleAdd}
                          placeholder="+ Add L3"
                        />
                      </div>
                    )}
                  </div>
                );
              })}
              <AddInline
                level={2}
                parentId={l1.id}
                disabled={busy}
                onAdd={handleAdd}
                placeholder="+ Add L2"
              />
            </div>
          </div>
        ))}
        <div className="kanban-col kanban-col-add">
          <AddInline
            level={1}
            parentId={null}
            disabled={busy}
            onAdd={handleAdd}
            placeholder="+ Add L1"
          />
        </div>
      </div>

      {confirmingDelete && (
        <div
          role="dialog"
          aria-label="Confirm delete capability"
          aria-modal="true"
          className="modal"
        >
          <div className="card">
            <h2>Delete capability?</h2>
            <p>
              This will remove &quot;{confirmingDelete.name}&quot; and all of
              its descendants.
            </p>
            <div className="form-actions">
              <button
                type="button"
                onClick={() => handleDelete(confirmingDelete)}
                disabled={busy}
                className="danger"
              >
                {busy ? "Deleting..." : "Yes, delete"}
              </button>
              <button
                type="button"
                onClick={() => setConfirmingDelete(null)}
                disabled={busy}
                className="link-button"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

function RowActions({
  onUp,
  onDown,
  onDelete,
  upDisabled,
  downDisabled,
  disabled,
  label,
}: {
  onUp: () => void;
  onDown: () => void;
  onDelete: () => void;
  upDisabled: boolean;
  downDisabled: boolean;
  disabled: boolean;
  label: string;
}) {
  return (
    <div className="kanban-actions">
      <button
        type="button"
        onClick={onUp}
        disabled={upDisabled}
        aria-label={`Move ${label} up`}
      >
        {"↑"}
      </button>
      <button
        type="button"
        onClick={onDown}
        disabled={downDisabled}
        aria-label={`Move ${label} down`}
      >
        {"↓"}
      </button>
      <button
        type="button"
        onClick={onDelete}
        disabled={disabled}
        className="danger"
        aria-label={`Delete ${label}`}
      >
        {"×"}
      </button>
    </div>
  );
}

function InlineText({
  value,
  onSave,
  placeholder,
  multiline,
  disabled,
  ariaLabel,
  className,
}: {
  value: string;
  onSave: (next: string) => void;
  placeholder?: string;
  multiline?: boolean;
  disabled?: boolean;
  ariaLabel?: string;
  className?: string;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);

  useEffect(() => {
    setDraft(value);
  }, [value]);

  function commit() {
    setEditing(false);
    if (draft !== value) onSave(draft);
  }

  function cancel() {
    setEditing(false);
    setDraft(value);
  }

  if (!editing) {
    return (
      <span
        role="button"
        tabIndex={0}
        className={`inline-text${value ? "" : " empty"}${className ? ` ${className}` : ""}`}
        onClick={() => {
          if (!disabled) setEditing(true);
        }}
        onKeyDown={(e: KeyboardEvent<HTMLSpanElement>) => {
          if ((e.key === "Enter" || e.key === " ") && !disabled) {
            e.preventDefault();
            setEditing(true);
          }
        }}
        aria-label={ariaLabel}
      >
        {value || placeholder || ""}
      </span>
    );
  }

  if (multiline) {
    return (
      <textarea
        autoFocus
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Escape") cancel();
        }}
        rows={2}
        aria-label={ariaLabel}
        className={className}
      />
    );
  }

  return (
    <input
      autoFocus
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          commit();
        } else if (e.key === "Escape") {
          cancel();
        }
      }}
      aria-label={ariaLabel}
      className={className}
    />
  );
}

function AddInline({
  level,
  parentId,
  disabled,
  onAdd,
  placeholder,
}: {
  level: CapabilityLevel;
  parentId: number | null;
  disabled?: boolean;
  onAdd: (
    level: CapabilityLevel,
    parentId: number | null,
    name: string,
  ) => Promise<void>;
  placeholder: string;
}) {
  const [active, setActive] = useState(false);
  const [name, setName] = useState("");

  if (!active) {
    return (
      <button
        type="button"
        className="kanban-add-button"
        onClick={() => setActive(true)}
        disabled={disabled}
      >
        {placeholder}
      </button>
    );
  }

  async function commit() {
    const trimmed = name.trim();
    setActive(false);
    setName("");
    if (trimmed) await onAdd(level, parentId, trimmed);
  }

  return (
    <input
      autoFocus
      value={name}
      onChange={(e) => setName(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          commit();
        } else if (e.key === "Escape") {
          setActive(false);
          setName("");
        }
      }}
      placeholder={`Name for new L${level}`}
      aria-label={`New L${level} name`}
      disabled={disabled}
    />
  );
}
