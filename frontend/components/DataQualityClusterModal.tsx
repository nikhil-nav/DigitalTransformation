"use client";

import { Loader2, X } from "lucide-react";
import { useEffect, useState } from "react";

import { api, ApiError, type DqClusterDetail } from "@/lib/api";
import { cn } from "@/lib/utils";

function scoreChipClass(score: number): string {
  return cn(
    "inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold",
    score >= 0.95 && "bg-[var(--jade)] text-white",
    score >= 0.8 && score < 0.95 && "bg-[var(--marigold)] text-[var(--pickled-bluewood)]",
    score < 0.8 && "bg-[var(--watermelon)] text-white",
  );
}

export default function DataQualityClusterModal({
  projectId,
  datasetId,
  runId,
  clusterId,
  sheetA,
  sheetB,
  onClose,
}: {
  projectId: number;
  datasetId: number;
  runId: number;
  clusterId: number;
  sheetA: string;
  sheetB: string;
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<DqClusterDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getSimilarityClusterDetail(projectId, datasetId, runId, clusterId)
      .then((d) => {
        if (!cancelled) setDetail(d);
      })
      .catch((e: unknown) => {
        if (!cancelled)
          setError(
            e instanceof ApiError ? e.message : "Failed to load cluster",
          );
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, datasetId, runId, clusterId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Build a union of column names across rows so the table headers stay
  // stable even when individual rows are missing columns.
  const columnsForRows = (
    rows: Array<Record<string, string | number | null>>,
  ): string[] => {
    const set = new Set<string>();
    for (const r of rows) {
      for (const k of Object.keys(r)) {
        if (k !== "_row_index") set.add(k);
      }
    }
    return Array.from(set);
  };

  return (
    <div
      role="dialog"
      aria-label="Cluster detail"
      aria-modal="true"
      className="fixed inset-0 z-40 grid place-items-center bg-black/30 p-4"
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="flex max-h-[85vh] w-full max-w-5xl flex-col overflow-hidden rounded-lg border border-[var(--geyser)] bg-white shadow-xl"
      >
        <header className="flex items-center justify-between gap-2 border-b border-[var(--geyser)] px-4 py-3">
          <h3 className="m-0 text-base font-semibold text-[var(--pickled-bluewood)]">
            Cluster detail
          </h3>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close cluster detail"
            className="grid h-7 w-7 place-items-center rounded text-[var(--slate)] hover:bg-[var(--fog)] hover:text-[var(--pickled-bluewood)]"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-4 py-4">
          {error && (
            <p role="alert" className="text-sm text-[var(--watermelon)]">
              {error}
            </p>
          )}
          {!error && !detail && (
            <div className="flex items-center gap-2 text-sm text-[var(--slate)]">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading cluster
              members...
            </div>
          )}

          {detail && (
            <div className="flex flex-col gap-4">
              {sheetA === sheetB ? (
                // Within-sheet dedup: every member is a row in the same
                // sheet. Merge a_members and b_members (by row index) so
                // the user sees one consolidated members list instead
                // of the same rows printed twice.
                (() => {
                  const merged = mergeRowsByIndex(
                    detail.a_rows,
                    detail.b_rows,
                  );
                  return (
                    <SidebySideTable
                      label={`${sheetA} (within-sheet dedup)`}
                      rows={merged}
                      columns={columnsForRows(merged)}
                    />
                  );
                })()
              ) : (
                <>
                  <SidebySideTable
                    label={sheetA}
                    rows={detail.a_rows}
                    columns={columnsForRows(detail.a_rows)}
                  />
                  <SidebySideTable
                    label={sheetB}
                    rows={detail.b_rows}
                    columns={columnsForRows(detail.b_rows)}
                  />
                </>
              )}

              <div>
                <h4 className="m-0 mb-2 text-sm font-semibold text-[var(--pickled-bluewood)]">
                  Pair-by-pair scores
                </h4>
                <table className="w-full border-collapse text-xs">
                  <thead>
                    <tr className="border-b border-[var(--geyser)] text-left text-[var(--slate)]">
                      <th className="px-2 py-1.5 font-medium">A row</th>
                      <th className="px-2 py-1.5 font-medium">B row</th>
                      <th className="px-2 py-1.5 font-medium">Overall</th>
                      <th className="px-2 py-1.5 font-medium">By column</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.pairs.map((p) => (
                      <tr
                        key={p.id}
                        className="border-b border-[var(--geyser)]"
                      >
                        <td className="px-2 py-1.5 font-mono text-[10px]">
                          {p.row_a_index}
                        </td>
                        <td className="px-2 py-1.5 font-mono text-[10px]">
                          {p.row_b_index}
                        </td>
                        <td className="px-2 py-1.5">
                          <span className={scoreChipClass(p.score)}>
                            {p.score.toFixed(3)}
                          </span>
                        </td>
                        <td className="px-2 py-1.5">
                          <span className="flex flex-wrap gap-1">
                            {Object.entries(p.per_column_scores).map(
                              ([k, v]) => (
                                <span
                                  key={k}
                                  className="inline-flex items-center gap-1 rounded-full bg-[var(--fog)] px-1.5 py-0.5 text-[10px]"
                                  title={k}
                                >
                                  <span className="text-[var(--slate)]">
                                    {k.split("|")[0]}
                                  </span>
                                  <span className={scoreChipClass(v)}>
                                    {v.toFixed(2)}
                                  </span>
                                </span>
                              ),
                            )}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * Merge two row arrays (representing the same sheet's A-side and B-side
 * members) by `_row_index`, so within-sheet dedup clusters show each row
 * once instead of duplicating rows that appeared on both sides of a pair.
 */
function mergeRowsByIndex(
  a: Array<Record<string, string | number | null>>,
  b: Array<Record<string, string | number | null>>,
): Array<Record<string, string | number | null>> {
  const byIdx = new Map<number, Record<string, string | number | null>>();
  for (const row of [...a, ...b]) {
    const idx = row._row_index;
    if (typeof idx === "number" && !byIdx.has(idx)) {
      byIdx.set(idx, row);
    }
  }
  return Array.from(byIdx.entries())
    .sort(([i], [j]) => i - j)
    .map(([, row]) => row);
}

function SidebySideTable({
  label,
  rows,
  columns,
}: {
  label: string;
  rows: Array<Record<string, string | number | null>>;
  columns: string[];
}) {
  if (rows.length === 0) {
    return (
      <div className="text-xs text-[var(--heather)]">
        No <strong>{label}</strong> members in this cluster.
      </div>
    );
  }
  return (
    <div>
      <h4 className="m-0 mb-1 text-sm font-semibold text-[var(--pickled-bluewood)]">
        {label} <span className="text-[var(--heather)]">({rows.length})</span>
      </h4>
      <div className="overflow-x-auto rounded-md border border-[var(--geyser)] bg-white">
        <table className="w-full border-collapse text-xs">
          <thead>
            <tr className="border-b border-[var(--geyser)] text-left text-[var(--slate)]">
              <th className="px-2 py-1 font-mono text-[10px]">#</th>
              {columns.map((c) => (
                <th key={c} className="px-2 py-1 font-medium">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="border-b border-[var(--geyser)]">
                <td className="px-2 py-1 font-mono text-[10px] text-[var(--heather)]">
                  {r._row_index ?? i}
                </td>
                {columns.map((c) => (
                  <td key={c} className="px-2 py-1">
                    {r[c] == null ? (
                      <span className="text-[var(--heather)]">—</span>
                    ) : (
                      String(r[c])
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
