"use client";

import { ChevronDown, Pencil, Plus, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { api, ApiError, type ChatThread } from "@/lib/api";
import { cn } from "@/lib/utils";

export default function ThreadList({
  projectId,
  activeThreadId,
  onActiveChange,
}: {
  projectId: number;
  activeThreadId: number | undefined;
  onActiveChange: (threadId: number | undefined) => void;
}) {
  const [threads, setThreads] = useState<ChatThread[]>([]);
  const [open, setOpen] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const popoverRef = useRef<HTMLDivElement>(null);

  // Load threads on mount and when project changes.
  useEffect(() => {
    let cancelled = false;
    api
      .listThreads(projectId)
      .then((list) => {
        if (cancelled) return;
        setThreads(list);
        if (list.length > 0 && activeThreadId === undefined) {
          onActiveChange(list[list.length - 1].id);
        }
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setError(
          e instanceof ApiError ? e.message : "Failed to load chat threads",
        );
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  // Close popover on outside click.
  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (
        popoverRef.current &&
        !popoverRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    };
    window.addEventListener("mousedown", onClick);
    return () => window.removeEventListener("mousedown", onClick);
  }, [open]);

  const active = threads.find((t) => t.id === activeThreadId);

  async function handleNew() {
    setBusy(true);
    setError(null);
    try {
      const created = await api.createThread(projectId);
      setThreads((prev) => [...prev, created]);
      onActiveChange(created.id);
      setOpen(false);
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : "Failed to create thread");
    } finally {
      setBusy(false);
    }
  }

  async function commitRename(id: number) {
    const title = editingTitle.trim();
    setEditingId(null);
    if (!title) return;
    try {
      const updated = await api.renameThread(projectId, id, title);
      setThreads((prev) => prev.map((t) => (t.id === id ? updated : t)));
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : "Failed to rename");
    }
  }

  async function handleDelete(id: number) {
    setBusy(true);
    setError(null);
    try {
      await api.deleteThread(projectId, id);
      setThreads((prev) => {
        const next = prev.filter((t) => t.id !== id);
        if (activeThreadId === id) {
          const fallback = next[next.length - 1];
          onActiveChange(fallback ? fallback.id : undefined);
        }
        return next;
      });
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : "Failed to delete");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="relative" ref={popoverRef}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex max-w-[14rem] items-center gap-1.5 rounded-md border border-[var(--geyser)] bg-white px-2.5 py-1 text-sm font-medium text-[var(--pickled-bluewood)] transition-colors hover:border-[var(--coral)] hover:text-[var(--coral)]"
        title="Switch chat thread"
      >
        <span className="truncate">{active ? active.title : "New chat"}</span>
        <ChevronDown
          className={cn(
            "h-3.5 w-3.5 shrink-0 transition-transform",
            open && "rotate-180",
          )}
        />
      </button>

      {open && (
        <div className="absolute left-0 top-full z-50 mt-1 w-72 rounded-lg border border-[var(--geyser)] bg-white p-1 shadow-lg">
          <div className="flex items-center justify-between border-b border-[var(--geyser)] px-2 py-1.5">
            <span className="text-xs font-semibold uppercase tracking-wide text-[var(--slate)]">
              Threads
            </span>
            <button
              type="button"
              onClick={handleNew}
              disabled={busy}
              className="inline-flex items-center gap-1 rounded-md border border-[var(--geyser)] bg-white px-2 py-0.5 text-xs font-medium text-[var(--pickled-bluewood)] hover:border-[var(--coral)] hover:text-[var(--coral)] disabled:opacity-50"
            >
              <Plus className="h-3 w-3" />
              New
            </button>
          </div>
          {threads.length === 0 ? (
            <p className="px-3 py-2 text-xs text-[var(--heather)]">
              No threads yet.
            </p>
          ) : (
            <ul className="max-h-64 overflow-y-auto">
              {threads.map((t) => {
                const isActive = t.id === activeThreadId;
                const isEditing = editingId === t.id;
                return (
                  <li
                    key={t.id}
                    className={cn(
                      "group flex items-center gap-1 rounded-md px-2 py-1.5 text-sm",
                      isActive
                        ? "bg-[var(--forget-me-not)] text-[var(--pickled-bluewood)]"
                        : "text-[var(--pickled-bluewood)] hover:bg-[var(--fog)]",
                    )}
                  >
                    {isEditing ? (
                      <input
                        autoFocus
                        value={editingTitle}
                        onChange={(e) => setEditingTitle(e.target.value)}
                        onBlur={() => commitRename(t.id)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") {
                            (e.target as HTMLInputElement).blur();
                          } else if (e.key === "Escape") {
                            setEditingId(null);
                          }
                        }}
                        className="flex-1 rounded border border-[var(--cerulean)] bg-white px-1 text-sm text-[var(--pickled-bluewood)] outline-none"
                      />
                    ) : (
                      <button
                        type="button"
                        onClick={() => {
                          onActiveChange(t.id);
                          setOpen(false);
                        }}
                        className="flex-1 truncate bg-transparent p-0 text-left text-inherit"
                        title={t.title}
                      >
                        {t.title}
                      </button>
                    )}
                    {!isEditing && (
                      <>
                        <button
                          type="button"
                          aria-label={`Rename ${t.title}`}
                          onClick={() => {
                            setEditingId(t.id);
                            setEditingTitle(t.title);
                          }}
                          className="grid h-6 w-6 place-items-center rounded text-[var(--slate)] opacity-0 hover:bg-[var(--geyser)] group-hover:opacity-100"
                        >
                          <Pencil className="h-3 w-3" />
                        </button>
                        <button
                          type="button"
                          aria-label={`Delete ${t.title}`}
                          disabled={busy || threads.length === 1}
                          onClick={() => handleDelete(t.id)}
                          className="grid h-6 w-6 place-items-center rounded text-[var(--slate)] opacity-0 hover:bg-[var(--geyser)] hover:text-[var(--watermelon)] group-hover:opacity-100 disabled:cursor-not-allowed disabled:opacity-30"
                        >
                          <Trash2 className="h-3 w-3" />
                        </button>
                      </>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
          {error && (
            <p className="mt-1 px-2 text-xs text-[var(--watermelon)]">
              {error}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
