"use client";

import {
  ChevronDown,
  ChevronRight,
  Download,
  GitBranch,
  Loader2,
  Maximize2,
  Pencil,
  Plus,
  Search,
  Trash2,
  X,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
} from "react";

import {
  api,
  ApiError,
  type Capability,
  type CapabilityLevel,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const L1_COLOURS = [
  "#1e3a52", // navy
  "#2f6f9f", // blue
  "#1f8a66", // green
  "#b5791c", // amber
  "#a6293a", // red
  "#5a6b8f", // slate-blue
  "#7a4f86", // plum
];

type LayoutName = "hierarchical" | "radial" | "concentric";

const LAYOUTS: { value: LayoutName; label: string }[] = [
  { value: "hierarchical", label: "Hierarchical" },
  { value: "radial", label: "Radial" },
  { value: "concentric", label: "Concentric" },
];

type GraphProps = {
  projectId: number;
  refreshKey?: number;
};

export default function BcmGraph({ projectId, refreshKey = 0 }: GraphProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<any>(null);
  const initialisedRef = useRef(false);

  const [capabilities, setCapabilities] = useState<Capability[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [cyReady, setCyReady] = useState(false);
  const [layout, setLayout] = useState<LayoutName>("hierarchical");
  const [searchQuery, setSearchQuery] = useState("");
  const [collapsedIds, setCollapsedIds] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState<Capability | null>(
    null,
  );
  const [internalRefresh, setInternalRefresh] = useState(0);

  // ---- Capability colours (by L1 lineage). ----
  const colourMap = useMemo(() => {
    if (!capabilities) return new Map<number, string>();
    const l1Order = capabilities
      .filter((c) => c.level === 1)
      .sort((a, b) => a.position - b.position);
    const byId = new Map<number, Capability>();
    for (const c of capabilities) byId.set(c.id, c);

    const map = new Map<number, string>();
    l1Order.forEach((l1, i) => {
      map.set(l1.id, L1_COLOURS[i % L1_COLOURS.length]);
    });
    for (const cap of capabilities) {
      if (cap.level === 1) continue;
      let cursor: Capability | undefined = cap;
      while (cursor && cursor.level !== 1) {
        cursor = cursor.parent_id ? byId.get(cursor.parent_id) : undefined;
      }
      if (cursor) map.set(cap.id, map.get(cursor.id) ?? L1_COLOURS[0]);
    }
    return map;
  }, [capabilities]);

  // ---- Capability children index (for collapse-aware rendering and rail copy). ----
  const childrenByParent = useMemo(() => {
    const m = new Map<number, Capability[]>();
    if (!capabilities) return m;
    for (const c of capabilities) {
      if (c.parent_id === null) continue;
      const list = m.get(c.parent_id);
      if (list) list.push(c);
      else m.set(c.parent_id, [c]);
    }
    return m;
  }, [capabilities]);

  function descendantsOf(id: number, out: Capability[] = []): Capability[] {
    for (const child of childrenByParent.get(id) ?? []) {
      out.push(child);
      descendantsOf(child.id, out);
    }
    return out;
  }

  // ---- Capabilities visible in the graph (after honouring collapse state). ----
  const visibleCapabilities = useMemo(() => {
    if (!capabilities) return null;
    if (collapsedIds.size === 0) return capabilities;

    const byId = new Map<number, Capability>();
    for (const c of capabilities) byId.set(c.id, c);

    const isHiddenDescendant = (c: Capability): boolean => {
      let cursor: Capability | undefined = c;
      while (cursor && cursor.parent_id !== null) {
        if (collapsedIds.has(cursor.parent_id)) return true;
        cursor = byId.get(cursor.parent_id);
      }
      return false;
    };
    return capabilities.filter((c) => !isHiddenDescendant(c));
  }, [capabilities, collapsedIds]);

  // ---- Lazy-init cytoscape on first mount. ----
  useEffect(() => {
    if (initialisedRef.current) return;
    let cancelled = false;

    (async () => {
      const cytoscapeMod = await import("cytoscape");
      const dagreMod = await import("cytoscape-dagre");
      if (cancelled || !containerRef.current) return;

      const cytoscape = cytoscapeMod.default;
      cytoscape.use(dagreMod.default);

      const cy = cytoscape({
        container: containerRef.current,
        elements: [],
        wheelSensitivity: 0.2,
        boxSelectionEnabled: false,
        autounselectify: false,
        style: [
          {
            selector: "node",
            style: {
              "background-color": "data(color)",
              "background-opacity": 0.9,
              label: "data(label)",
              "font-family":
                '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
              color: "#1e3a52",
              "font-weight": 600,
              "text-valign": "center",
              "text-halign": "center",
              "text-wrap": "wrap",
              "text-max-width": "120px",
              "border-width": 1,
              "border-color": "#dde4ec",
              shape: "round-rectangle",
              "transition-property": "opacity, background-opacity",
              "transition-duration": "150ms" as any,
            },
          },
          {
            selector: "node[level = 1]",
            style: {
              width: 160,
              height: 56,
              "font-size": 13,
              "background-opacity": 1,
              color: "#ffffff",
              "border-width": 0,
            },
          },
          {
            selector: "node[level = 2]",
            style: {
              width: 130,
              height: 44,
              "font-size": 12,
              "background-opacity": 0.65,
            },
          },
          {
            selector: "node[level = 3]",
            style: {
              width: 110,
              height: 34,
              "font-size": 11,
              "background-opacity": 0.4,
            },
          },
          {
            selector: "node[?hasHidden]",
            style: {
              "border-width": 2,
              "border-color": "#1e3a52",
              "border-style": "dashed",
            },
          },
          {
            selector: "node:selected",
            style: {
              "border-width": 3,
              "border-color": "#2f6f9f",
            },
          },
          { selector: "node.faded", style: { opacity: 0.18 } },
          { selector: "node.search-miss", style: { opacity: 0.12 } },
          {
            selector: "node.search-hit",
            style: {
              "border-width": 3,
              "border-color": "#e0a53c",
            },
          },
          {
            selector: "edge",
            style: {
              width: 1.5,
              "line-color": "#8497ac",
              "curve-style": "taxi",
              "taxi-direction": "downward",
              "taxi-turn": 24,
              "target-arrow-shape": "none",
            },
          },
          { selector: "edge.faded", style: { opacity: 0.1 } },
          { selector: "edge.search-miss", style: { opacity: 0.08 } },
        ],
        layout: { name: "preset" },
      });

      cy.on("tap", "node", (e: { target: { id: () => string } }) => {
        const id = parseInt(e.target.id().replace("cap-", ""), 10);
        setSelectedId(Number.isFinite(id) ? id : null);
      });
      cy.on("tap", (e: { target: unknown }) => {
        if (e.target === cy) setSelectedId(null);
      });
      cy.on("mouseover", "node", (e: { target: any }) => {
        const node = e.target;
        const lineage = node
          .successors()
          .union(node.predecessors())
          .union(node);
        cy.elements().not(lineage).addClass("faded");
      });
      cy.on("mouseout", "node", () => {
        cy.elements().removeClass("faded");
      });

      cyRef.current = cy;
      initialisedRef.current = true;
      setCyReady(true);
    })();

    return () => {
      cancelled = true;
      if (cyRef.current) {
        cyRef.current.destroy();
        cyRef.current = null;
      }
      initialisedRef.current = false;
      setCyReady(false);
    };
  }, []);

  // ---- Fetch capabilities. ----
  useEffect(() => {
    let cancelled = false;
    setCapabilities(null);
    api
      .listCapabilities(projectId)
      .then((list) => {
        if (!cancelled) setCapabilities(list);
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          setError(
            e instanceof ApiError ? e.message : "Failed to load capabilities",
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, refreshKey, internalRefresh]);

  // ---- Re-render the graph when visible capabilities or layout change. ----
  useEffect(() => {
    if (!cyReady || !cyRef.current || !visibleCapabilities) return;
    const cy = cyRef.current;

    const nodes = visibleCapabilities.map((c) => ({
      data: {
        id: `cap-${c.id}`,
        label: c.name,
        level: c.level,
        color: colourMap.get(c.id) ?? L1_COLOURS[0],
        hasHidden: collapsedIds.has(c.id),
      },
    }));
    const edges = visibleCapabilities
      .filter((c) => c.parent_id !== null)
      .map((c) => ({
        data: {
          id: `e-${c.id}`,
          source: `cap-${c.parent_id}`,
          target: `cap-${c.id}`,
        },
      }));

    cy.elements().remove();
    cy.add([...nodes, ...edges]);

    if (nodes.length === 0) return;

    cy.layout(buildLayoutOptions(layout)).run();
  }, [visibleCapabilities, colourMap, cyReady, layout, collapsedIds]);

  // ---- Resize cytoscape when the right rail toggles. ----
  useEffect(() => {
    if (!cyRef.current) return;
    const cy = cyRef.current;
    const t = setTimeout(() => {
      cy.resize();
      cy.fit(undefined, 32);
    }, 220);
    return () => clearTimeout(t);
  }, [selectedId]);

  // ---- Search highlight. ----
  useEffect(() => {
    if (!cyRef.current) return;
    const cy = cyRef.current;
    const q = searchQuery.trim().toLowerCase();
    if (!q) {
      cy.elements().removeClass("search-miss").removeClass("search-hit");
      return;
    }
    cy.batch(() => {
      cy.nodes().forEach((n: any) => {
        const label = String(n.data("label") || "").toLowerCase();
        if (label.includes(q)) {
          n.addClass("search-hit").removeClass("search-miss");
        } else {
          n.addClass("search-miss").removeClass("search-hit");
        }
      });
      cy.edges().forEach((e: any) => {
        const sourceHit = e.source().hasClass("search-hit");
        const targetHit = e.target().hasClass("search-hit");
        if (sourceHit || targetHit) {
          e.removeClass("search-miss");
        } else {
          e.addClass("search-miss");
        }
      });
    });
  }, [searchQuery, visibleCapabilities]);

  // ---- Selected capability helpers. ----
  const selected = useMemo(
    () => capabilities?.find((c) => c.id === selectedId) ?? null,
    [capabilities, selectedId],
  );
  const selectedParent = useMemo(() => {
    if (!selected || selected.parent_id === null || !capabilities) return null;
    return capabilities.find((c) => c.id === selected.parent_id) ?? null;
  }, [selected, capabilities]);
  const selectedDirectChildren = useMemo(() => {
    if (!selected) return [];
    return childrenByParent.get(selected.id) ?? [];
  }, [selected, childrenByParent]);

  // ---- Toolbar actions. ----
  const handleFit = useCallback(() => {
    cyRef.current?.fit(undefined, 32);
  }, []);

  const handleExport = useCallback(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const png: string = cy.png({ scale: 2, full: true, bg: "#ffffff" });
    const a = document.createElement("a");
    a.href = png;
    a.download = `bcm-project-${projectId}.png`;
    a.click();
  }, [projectId]);

  // ---- Edits. ----
  async function withBusy<T>(fn: () => Promise<T>): Promise<T | null> {
    setBusy(true);
    setError(null);
    try {
      return await fn();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Action failed");
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function handleRename(cap: Capability, name: string) {
    const trimmed = name.trim();
    if (!trimmed || trimmed === cap.name) return;
    const ok = await withBusy(() =>
      api.updateCapability(projectId, cap.id, { name: trimmed }),
    );
    if (ok) setInternalRefresh((n) => n + 1);
  }

  async function handleEditDescription(cap: Capability, description: string) {
    const next = description.trim() ? description.trim() : null;
    if (next === (cap.description ?? null)) return;
    const ok = await withBusy(() =>
      api.updateCapability(projectId, cap.id, { description: next }),
    );
    if (ok) setInternalRefresh((n) => n + 1);
  }

  async function handleAddChild(parent: Capability) {
    if (parent.level >= 3) return;
    const ok = await withBusy(() =>
      api.createCapability(projectId, {
        level: (parent.level + 1) as CapabilityLevel,
        parent_id: parent.id,
        name: "New capability",
      }),
    );
    if (ok) {
      setCollapsedIds((prev) => {
        if (!prev.has(parent.id)) return prev;
        const next = new Set(prev);
        next.delete(parent.id);
        return next;
      });
      setInternalRefresh((n) => n + 1);
    }
  }

  async function handleDelete(cap: Capability) {
    const ok = await withBusy(() => api.deleteCapability(projectId, cap.id));
    setConfirmingDelete(null);
    if (ok !== null) {
      setSelectedId(null);
      setCollapsedIds((prev) => {
        if (!prev.has(cap.id)) return prev;
        const next = new Set(prev);
        next.delete(cap.id);
        return next;
      });
      setInternalRefresh((n) => n + 1);
    }
  }

  function toggleCollapse(cap: Capability) {
    setCollapsedIds((prev) => {
      const next = new Set(prev);
      if (next.has(cap.id)) next.delete(cap.id);
      else next.add(cap.id);
      return next;
    });
  }

  const isEmpty = capabilities !== null && capabilities.length === 0;

  return (
    <section className="card flex h-[72vh] min-h-[500px] flex-col overflow-hidden !p-0">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--geyser)] px-4 py-3">
        <div className="flex items-center gap-2">
          <GitBranch className="h-4 w-4 text-[var(--cerulean)]" />
          <h2 className="m-0 text-base font-semibold text-[var(--pickled-bluewood)]">
            Capability graph
          </h2>
          {capabilities && (
            <span className="text-xs text-[var(--slate)]">
              {capabilities.filter((c) => c.level === 1).length} L1
              {capabilities.filter((c) => c.level === 1).length === 1 ? "" : "s"}
              {" · "}
              {capabilities.length} node
              {capabilities.length === 1 ? "" : "s"}
            </span>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <SearchBox value={searchQuery} onChange={setSearchQuery} />
          <LayoutPicker layout={layout} onChange={setLayout} />
          <button
            type="button"
            onClick={handleFit}
            disabled={!cyReady || isEmpty}
            className={toolbarBtn}
            aria-label="Fit graph to view"
          >
            <Maximize2 className="h-3.5 w-3.5" />
            <span>Fit</span>
          </button>
          <button
            type="button"
            onClick={handleExport}
            disabled={!cyReady || isEmpty}
            className={toolbarBtn}
            aria-label="Export PNG"
          >
            <Download className="h-3.5 w-3.5" />
            <span>PNG</span>
          </button>
        </div>
      </header>
      {error && (
        <div
          role="alert"
          className="mx-4 mt-3 rounded-md border border-[var(--watermelon)] bg-white px-3 py-2 text-sm text-[var(--watermelon)]"
        >
          {error}
        </div>
      )}
      <div className="relative flex flex-1 min-h-0 overflow-hidden">
        <div className="relative flex-1">
          {!cyReady && capabilities === null && (
            <div className="absolute inset-0 grid place-items-center">
              <Loader2 className="h-5 w-5 animate-spin text-[var(--slate)]" />
            </div>
          )}
          {isEmpty && (
            <div className="absolute inset-0 grid place-items-center px-6 text-center text-sm text-[var(--slate)]">
              No capabilities yet. Add some on the Board tab, or ask the chat
              agent to draft a BCM.
            </div>
          )}
          <div
            ref={containerRef}
            className={cn(
              "h-full w-full bg-[var(--fog)]",
              isEmpty && "opacity-0",
            )}
          />
        </div>
        {selected && (
          <DetailsRail
            capability={selected}
            parent={selectedParent}
            directChildren={selectedDirectChildren}
            isCollapsed={collapsedIds.has(selected.id)}
            descendantHiddenCount={
              collapsedIds.has(selected.id)
                ? descendantsOf(selected.id).length
                : 0
            }
            busy={busy}
            onClose={() => setSelectedId(null)}
            onRename={(value) => handleRename(selected, value)}
            onEditDescription={(value) =>
              handleEditDescription(selected, value)
            }
            onAddChild={() => handleAddChild(selected)}
            onConfirmDelete={() => setConfirmingDelete(selected)}
            onToggleCollapse={() => toggleCollapse(selected)}
          />
        )}
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
                className="danger"
                onClick={() => handleDelete(confirmingDelete)}
                disabled={busy}
              >
                {busy ? "Deleting..." : "Yes, delete"}
              </button>
              <button
                type="button"
                className="link-button"
                onClick={() => setConfirmingDelete(null)}
                disabled={busy}
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

const toolbarBtn =
  "inline-flex items-center gap-1.5 rounded-md border border-[var(--geyser)] bg-white px-2 py-1 text-xs text-[var(--pickled-bluewood)] transition-all hover:border-[var(--coral)] hover:text-[var(--coral)] disabled:cursor-not-allowed disabled:opacity-50";

function SearchBox({
  value,
  onChange,
}: {
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="relative">
      <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--slate)]" />
      <input
        type="text"
        value={value}
        onChange={(e: ChangeEvent<HTMLInputElement>) => onChange(e.target.value)}
        placeholder="Search capabilities..."
        aria-label="Search capabilities"
        className="h-7 w-44 rounded-md border border-[var(--geyser)] bg-white pl-7 pr-2 text-xs text-[var(--pickled-bluewood)] placeholder:text-[var(--heather)] focus:border-[var(--cerulean)] focus:outline-none focus:ring-2 focus:ring-[var(--cerulean)]/20"
      />
      {value && (
        <button
          type="button"
          aria-label="Clear search"
          onClick={() => onChange("")}
          className="absolute right-1 top-1/2 grid h-5 w-5 -translate-y-1/2 place-items-center rounded text-[var(--slate)] hover:bg-[var(--fog)]"
        >
          <X className="h-3 w-3" />
        </button>
      )}
    </div>
  );
}

function LayoutPicker({
  layout,
  onChange,
}: {
  layout: LayoutName;
  onChange: (l: LayoutName) => void;
}) {
  return (
    <select
      value={layout}
      onChange={(e) => onChange(e.target.value as LayoutName)}
      aria-label="Graph layout"
      className="h-7 rounded-md border border-[var(--geyser)] bg-white px-2 text-xs text-[var(--pickled-bluewood)] focus:border-[var(--cerulean)] focus:outline-none"
    >
      {LAYOUTS.map((l) => (
        <option key={l.value} value={l.value}>
          {l.label}
        </option>
      ))}
    </select>
  );
}

function buildLayoutOptions(layout: LayoutName) {
  const baseAnimate = {
    animate: true,
    animationDuration: 400,
    fit: true,
    padding: 24,
  };
  switch (layout) {
    case "hierarchical":
      return {
        ...baseAnimate,
        name: "dagre",
        rankDir: "TB",
        nodeSep: 28,
        rankSep: 70,
        edgeSep: 16,
      } as any;
    case "radial":
      return {
        ...baseAnimate,
        name: "breadthfirst",
        circle: true,
        spacingFactor: 1.6,
        directed: true,
      } as any;
    case "concentric":
      return {
        ...baseAnimate,
        name: "concentric",
        concentric: (n: any) => 4 - Number(n.data("level") ?? 1),
        levelWidth: () => 1,
        minNodeSpacing: 30,
      } as any;
  }
}

function DetailsRail({
  capability,
  parent,
  directChildren,
  isCollapsed,
  descendantHiddenCount,
  busy,
  onClose,
  onRename,
  onEditDescription,
  onAddChild,
  onConfirmDelete,
  onToggleCollapse,
}: {
  capability: Capability;
  parent: Capability | null;
  directChildren: Capability[];
  isCollapsed: boolean;
  descendantHiddenCount: number;
  busy: boolean;
  onClose: () => void;
  onRename: (next: string) => void;
  onEditDescription: (next: string) => void;
  onAddChild: () => void;
  onConfirmDelete: () => void;
  onToggleCollapse: () => void;
}) {
  return (
    <aside className="flex w-80 shrink-0 flex-col gap-3 overflow-y-auto border-l border-[var(--geyser)] bg-white p-4">
      <div className="flex items-start justify-between gap-2">
        <span className="rounded-full border border-[var(--geyser)] bg-[var(--fog)] px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-[var(--slate)]">
          L{capability.level}
        </span>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close details"
          className="grid h-7 w-7 place-items-center rounded-md text-[var(--slate)] hover:bg-[var(--fog)] hover:text-[var(--pickled-bluewood)]"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="flex flex-col gap-1">
        <span className="text-[10px] font-semibold uppercase tracking-wide text-[var(--slate)]">
          Name
        </span>
        <InlineText
          value={capability.name}
          onSave={onRename}
          disabled={busy}
          className="text-base font-semibold text-[var(--pickled-bluewood)]"
        />
        {parent && (
          <p className="text-xs text-[var(--slate)]">
            Under: <span className="font-medium">{parent.name}</span>
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1">
        <span className="text-[10px] font-semibold uppercase tracking-wide text-[var(--slate)]">
          Description
        </span>
        <InlineText
          value={capability.description ?? ""}
          onSave={onEditDescription}
          disabled={busy}
          multiline
          placeholder="Add description..."
          className="text-sm text-[var(--pickled-bluewood)]"
        />
      </div>

      {directChildren.length > 0 && (
        <button
          type="button"
          onClick={onToggleCollapse}
          disabled={busy}
          className="inline-flex items-center justify-between gap-2 rounded-md border border-[var(--geyser)] bg-white px-2.5 py-1.5 text-xs text-[var(--pickled-bluewood)] hover:border-[var(--coral)] hover:text-[var(--coral)] disabled:opacity-50"
        >
          <span className="flex items-center gap-1.5">
            {isCollapsed ? (
              <ChevronRight className="h-3.5 w-3.5" />
            ) : (
              <ChevronDown className="h-3.5 w-3.5" />
            )}
            {isCollapsed
              ? `Expand subtree (${descendantHiddenCount} hidden)`
              : `Collapse subtree (${directChildren.length} direct)`}
          </span>
        </button>
      )}

      <div className="mt-2 flex flex-col gap-1.5">
        {capability.level < 3 && (
          <button
            type="button"
            onClick={onAddChild}
            disabled={busy}
            className="inline-flex items-center gap-1.5 rounded-md border border-[var(--geyser)] bg-white px-2.5 py-1.5 text-xs text-[var(--pickled-bluewood)] hover:border-[var(--coral)] hover:text-[var(--coral)] disabled:opacity-50"
          >
            <Plus className="h-3.5 w-3.5" />
            Add L{capability.level + 1}
          </button>
        )}
        <button
          type="button"
          onClick={onConfirmDelete}
          disabled={busy}
          className="inline-flex items-center gap-1.5 rounded-md border border-[var(--geyser)] bg-white px-2.5 py-1.5 text-xs text-[var(--watermelon)] hover:border-[var(--watermelon)] hover:bg-[var(--watermelon)]/10 disabled:opacity-50"
        >
          <Trash2 className="h-3.5 w-3.5" />
          Delete capability
        </button>
      </div>

      <p className="mt-auto text-xs text-[var(--heather)]">
        Tip: rename inline by clicking the name or description; the Board tab
        also supports drag-style reordering with up/down buttons.
      </p>
    </aside>
  );
}

function InlineText({
  value,
  onSave,
  placeholder,
  multiline,
  disabled,
  className,
}: {
  value: string;
  onSave: (next: string) => void;
  placeholder?: string;
  multiline?: boolean;
  disabled?: boolean;
  className?: string;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);

  useEffect(() => {
    setDraft(value);
  }, [value]);

  if (!editing) {
    return (
      <button
        type="button"
        onClick={() => !disabled && setEditing(true)}
        disabled={disabled}
        className={cn(
          "group flex items-start gap-1.5 rounded border border-transparent px-1.5 py-1 text-left transition-colors hover:border-[var(--geyser)] disabled:cursor-not-allowed disabled:opacity-50",
          !value && "italic text-[var(--heather)]",
          className,
        )}
      >
        <span className="flex-1 whitespace-pre-wrap break-words">
          {value || placeholder || ""}
        </span>
        <Pencil className="mt-0.5 h-3 w-3 shrink-0 text-[var(--heather)] opacity-0 group-hover:opacity-100" />
      </button>
    );
  }

  function commit() {
    setEditing(false);
    onSave(draft);
  }

  function cancel() {
    setEditing(false);
    setDraft(value);
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
        rows={3}
        className={cn(
          "rounded border border-[var(--cerulean)] bg-white px-2 py-1 text-sm text-[var(--pickled-bluewood)] focus:outline-none focus:ring-2 focus:ring-[var(--cerulean)]/20",
          className,
        )}
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
      className={cn(
        "rounded border border-[var(--cerulean)] bg-white px-2 py-1 text-sm text-[var(--pickled-bluewood)] focus:outline-none focus:ring-2 focus:ring-[var(--cerulean)]/20",
        className,
      )}
    />
  );
}
