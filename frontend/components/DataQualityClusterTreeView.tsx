"use client";

import { CheckCircle2, Download, Loader2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import {
  api,
  ApiError,
  type DqClusterTree,
  type DqGoldenValue,
} from "@/lib/api";
import { cn } from "@/lib/utils";

import DataQualityTreeEditor from "./DataQualityTreeEditor";
import DataQualityTreeVisualizer from "./DataQualityTreeVisualizer";

type SubTab = "edit" | "visualize";

/**
 * Tree-tab orchestrator: loads the cluster tree, owns the save handlers,
 * and routes between the HTML-form Edit sub-tab (where the user picks
 * golden values) and the Cytoscape Visualize sub-tab (a read-only graph
 * of the RESOLVED golden record — only leaves with explicit picks).
 */
export default function DataQualityClusterTreeView({
  projectId,
  datasetId,
  runId,
  clusterId,
}: {
  projectId: number;
  datasetId: number;
  runId: number;
  clusterId: number;
}) {
  const [tree, setTree] = useState<DqClusterTree | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [savingColumn, setSavingColumn] = useState<string | null>(null);
  const [subTab, setSubTab] = useState<SubTab>("edit");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const t = await api.getClusterTree(projectId, datasetId, runId, clusterId);
      setTree(t);
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : "Failed to load tree");
    } finally {
      setLoading(false);
    }
  }, [projectId, datasetId, runId, clusterId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleSetGolden(
    columnName: string,
    chosenValue: DqGoldenValue,
  ) {
    setSavingColumn(columnName);
    setError(null);
    try {
      const t = await api.setClusterGolden(
        projectId,
        datasetId,
        runId,
        clusterId,
        { column_name: columnName, chosen_value: chosenValue },
      );
      setTree(t);
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : "Save failed");
    } finally {
      setSavingColumn(null);
    }
  }

  async function handleClearGolden(columnName: string) {
    setSavingColumn(columnName);
    setError(null);
    try {
      const t = await api.clearClusterGolden(
        projectId,
        datasetId,
        runId,
        clusterId,
        columnName,
      );
      setTree(t);
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : "Reset failed");
    } finally {
      setSavingColumn(null);
    }
  }

  function handleExport() {
    if (!tree) return;
    const blob = new Blob([JSON.stringify(buildExport(tree), null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `cluster-${clusterId}-merged.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-sm text-[var(--slate)]">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading tree...
      </div>
    );
  }
  if (error) {
    return (
      <p role="alert" className="text-sm text-[var(--watermelon)]">
        {error}
      </p>
    );
  }
  if (!tree) return null;

  const resolvedFraction =
    tree.conflict_count === 0
      ? "no conflicts"
      : `${tree.resolved_conflict_count} of ${tree.conflict_count} conflicts resolved`;

  return (
    <div className="flex flex-col gap-3">
      {/* Header pill */}
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-[var(--geyser)] bg-[var(--fog)] px-3 py-2">
        <div className="flex items-center gap-2">
          <span className="text-xs text-[var(--slate)]">
            {tree.master_record
              ? `${tree.master_record.tag}:`
              : `Root (${tree.root_display_name}):`}
          </span>
          <span className="font-mono text-sm font-semibold text-[var(--pickled-bluewood)]">
            {renderGoldenValue(tree.root_value)}
          </span>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <span
            className={cn(
              "inline-flex items-center gap-1 rounded-full px-2 py-0.5",
              tree.conflict_count === 0 ||
                tree.resolved_conflict_count === tree.conflict_count
                ? "bg-[var(--jade)] text-white"
                : "bg-[var(--marigold)] text-[var(--pickled-bluewood)]",
            )}
          >
            <CheckCircle2 className="h-3 w-3" />
            {resolvedFraction}
          </span>
          <button
            type="button"
            onClick={handleExport}
            className="inline-flex items-center gap-1 rounded border border-[var(--geyser)] bg-white px-2 py-1 text-[var(--pickled-bluewood)] hover:border-[var(--pickled-bluewood)]"
          >
            <Download className="h-3 w-3" /> Export merged record
          </button>
        </div>
      </div>

      {/* Sub-tabs */}
      <div
        role="tablist"
        aria-label="Tree view mode"
        className="flex items-center gap-1 border-b border-[var(--geyser)]"
      >
        <SubTabButton
          label="Edit"
          active={subTab === "edit"}
          onClick={() => setSubTab("edit")}
        />
        <SubTabButton
          label="Visualize golden record"
          active={subTab === "visualize"}
          onClick={() => setSubTab("visualize")}
        />
      </div>

      {/* Sub-tab body. Editor and visualizer are mounted/unmounted on
          switch — the visualizer's Cytoscape init is cheap and benefits
          from being torn down when hidden. */}
      {subTab === "edit" ? (
        <DataQualityTreeEditor
          tree={tree}
          savingColumn={savingColumn}
          onSet={handleSetGolden}
          onClear={handleClearGolden}
        />
      ) : (
        <DataQualityTreeVisualizer tree={tree} />
      )}
    </div>
  );
}

function SubTabButton({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={cn(
        "rounded-t border-b-2 px-3 py-1.5 text-xs font-medium transition-colors",
        active
          ? "border-[var(--pickled-bluewood)] bg-white text-[var(--pickled-bluewood)]"
          : "border-transparent text-[var(--slate)] hover:bg-white hover:text-[var(--pickled-bluewood)]",
      )}
    >
      {label}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Export helpers (exported for unit testing)
// ---------------------------------------------------------------------------

export function buildExport(tree: DqClusterTree): unknown {
  if (tree.master_record) {
    return {
      master_tag: tree.master_record.tag,
      root_column: tree.master_record.root_column_a,
      subtrees: tree.master_record.subtrees.map((st) => ({
        variant: st.variant_raw,
        attributes: groupsToObject(st.subtree),
      })),
    };
  }
  return groupsToObject(tree);
}

function groupsToObject(tree: DqClusterTree): Record<string, DqGoldenValue> {
  const out: Record<string, DqGoldenValue> = {};
  out[tree.root_column_a] = tree.root_value;
  for (const g of tree.groups) {
    for (const l of g.leaves) {
      out[l.column_a] = l.chosen;
    }
  }
  return out;
}

function renderGoldenValue(v: DqGoldenValue): React.ReactNode {
  if (v === null) return <span className="text-[var(--heather)]">(null)</span>;
  if (Array.isArray(v)) {
    if (v.length === 0)
      return <span className="text-[var(--heather)]">(empty)</span>;
    return <span>{v.join(" · ")}</span>;
  }
  return <span>{v}</span>;
}
