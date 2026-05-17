"use client";

import {
  AlertTriangle,
  CheckCircle2,
  Loader2,
  Pencil,
  Play,
  Sparkles,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import {
  api,
  ApiError,
  type DqRecordCluster,
  type DqSimilarityRun,
} from "@/lib/api";
import { cn } from "@/lib/utils";

import DataQualityClusterModal from "./DataQualityClusterModal";

function fmtTimestamp(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function scoreChipClass(score: number): string {
  return cn(
    "inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold",
    score >= 0.95 && "bg-[var(--jade)] text-white",
    score >= 0.8 && score < 0.95 && "bg-[var(--marigold)] text-[var(--pickled-bluewood)]",
    score < 0.8 && "bg-[var(--watermelon)] text-white",
  );
}

function statusChipClass(status: DqSimilarityRun["status"]): string {
  return cn(
    "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
    status === "done" && "bg-[var(--jade)] text-white",
    status === "running" && "bg-[var(--cerulean)] text-white",
    status === "failed" && "bg-[var(--watermelon)] text-white",
  );
}

export default function DataQualitySimilarityTab({
  projectId,
  datasetId,
  onEditConfig,
}: {
  projectId: number;
  datasetId: number;
  onEditConfig: () => void;
}) {
  const [runs, setRuns] = useState<DqSimilarityRun[] | null>(null);
  const [clusters, setClusters] = useState<DqRecordCluster[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [selectedClusterId, setSelectedClusterId] = useState<number | null>(null);

  const latest = runs && runs.length > 0 ? runs[0] : null;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const runsList = await api.listSimilarityRuns(projectId, datasetId);
      setRuns(runsList);
      if (runsList.length === 0) {
        setClusters([]);
        return;
      }
      const cs = await api.listSimilarityClusters(
        projectId,
        datasetId,
        runsList[0].id,
      );
      setClusters(cs);
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : "Failed to load runs");
    } finally {
      setLoading(false);
    }
  }, [projectId, datasetId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleRerun() {
    setRunning(true);
    setError(null);
    try {
      await api.runSimilarity(projectId, datasetId);
      await load();
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : "Re-run failed");
    } finally {
      setRunning(false);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-sm text-[var(--slate)]">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading similarity runs...
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-sm text-[var(--pickled-bluewood)]">
          <Sparkles className="h-4 w-4 text-[var(--cerulean)]" />
          <span className="font-medium">Record-level similarity</span>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onEditConfig}
            className="inline-flex items-center gap-1 rounded border border-[var(--geyser)] bg-white px-2 py-1 text-xs text-[var(--pickled-bluewood)] hover:border-[var(--cerulean)] hover:text-[var(--cerulean)]"
          >
            <Pencil className="h-3 w-3" /> Edit config
          </button>
          <button
            type="button"
            onClick={() => void handleRerun()}
            disabled={running}
            className="inline-flex items-center gap-1 rounded bg-[var(--coral)] px-2 py-1 text-xs font-medium text-white hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {running ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <Play className="h-3 w-3" />
            )}
            {running ? "Running..." : "Re-run"}
          </button>
        </div>
      </div>

      {error && (
        <div
          role="alert"
          className="rounded-md border border-[var(--watermelon)] bg-white px-3 py-2 text-sm text-[var(--watermelon)]"
        >
          {error}
        </div>
      )}

      {!latest && (
        <div className="rounded-md border border-dashed border-[var(--geyser)] bg-white px-4 py-6 text-center text-sm text-[var(--heather)]">
          No similarity runs yet. Click <strong>Re-run</strong> above to
          execute against the saved configuration.
        </div>
      )}

      {latest && (
        <div className="rounded-md border border-[var(--geyser)] bg-white p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <span className={statusChipClass(latest.status)}>
                {latest.status === "done" ? (
                  <CheckCircle2 className="h-3 w-3" />
                ) : latest.status === "failed" ? (
                  <AlertTriangle className="h-3 w-3" />
                ) : (
                  <Loader2 className="h-3 w-3 animate-spin" />
                )}
                {latest.status}
              </span>
              <span className="text-sm font-medium text-[var(--pickled-bluewood)]">
                {latest.sheet_a === latest.sheet_b
                  ? `${latest.sheet_a} (within-sheet dedup)`
                  : `${latest.sheet_a} ↔ ${latest.sheet_b}`}
              </span>
              <span className="text-xs text-[var(--slate)]">
                threshold {latest.threshold.toFixed(2)}
              </span>
            </div>
            <span className="text-xs text-[var(--heather)]">
              {fmtTimestamp(latest.finished_at ?? latest.started_at)}
            </span>
          </div>
          <div className="mt-2 grid grid-cols-2 gap-2 text-xs text-[var(--slate)] sm:grid-cols-4">
            <Stat label="Candidate pairs" value={latest.candidate_pair_count} />
            <Stat label="Passing pairs" value={latest.passing_pair_count} />
            <Stat label="Clusters" value={latest.cluster_count} />
            <Stat
              label="Blocking"
              value={latest.blocking_column ?? "brute force"}
            />
          </div>
          {latest.error && (
            <p className="mt-2 text-xs text-[var(--watermelon)]">
              {latest.error}
            </p>
          )}
        </div>
      )}

      {/* Cluster table */}
      {latest && latest.status === "done" && (
        <div className="rounded-md border border-[var(--geyser)] bg-white">
          {clusters.length === 0 ? (
            <p className="p-4 text-sm text-[var(--heather)]">
              No clusters at this threshold. Try lowering the threshold or
              relaxing the important-column constraints in the config.
            </p>
          ) : (
            <table
              className="w-full border-collapse text-xs"
              aria-label="Similarity clusters"
            >
              <thead>
                <tr className="border-b border-[var(--geyser)] text-left text-[var(--slate)]">
                  <th className="px-2 py-1.5 font-medium">#</th>
                  <th className="px-2 py-1.5 font-medium">Canonical key</th>
                  {latest.sheet_a === latest.sheet_b ? (
                    <th className="px-2 py-1.5 font-medium">Members</th>
                  ) : (
                    <>
                      <th className="px-2 py-1.5 font-medium">A members</th>
                      <th className="px-2 py-1.5 font-medium">B members</th>
                    </>
                  )}
                  <th className="px-2 py-1.5 font-medium">Top</th>
                  <th className="px-2 py-1.5 font-medium">Min</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {clusters.map((c) => (
                  <tr key={c.id} className="border-b border-[var(--geyser)]">
                    <td className="px-2 py-1.5 text-[var(--slate)]">
                      {c.cluster_index}
                    </td>
                    <td className="px-2 py-1.5 text-[var(--pickled-bluewood)]">
                      <CanonicalKeyCell value={c.canonical_key} />
                    </td>
                    {latest.sheet_a === latest.sheet_b ? (
                      <td className="px-2 py-1.5">
                        {new Set([...c.a_members, ...c.b_members]).size}
                      </td>
                    ) : (
                      <>
                        <td className="px-2 py-1.5">{c.a_member_count}</td>
                        <td className="px-2 py-1.5">{c.b_member_count}</td>
                      </>
                    )}
                    <td className="px-2 py-1.5">
                      <span className={scoreChipClass(c.top_score)}>
                        {c.top_score.toFixed(2)}
                      </span>
                    </td>
                    <td className="px-2 py-1.5">
                      <span className={scoreChipClass(c.min_score)}>
                        {c.min_score.toFixed(2)}
                      </span>
                    </td>
                    <td className="px-2 py-1.5">
                      <button
                        type="button"
                        onClick={() => setSelectedClusterId(c.id)}
                        aria-label={`View cluster ${c.cluster_index}`}
                        className="rounded border border-[var(--geyser)] bg-white px-2 py-0.5 text-[10px] text-[var(--pickled-bluewood)] hover:border-[var(--cerulean)] hover:text-[var(--cerulean)]"
                      >
                        View
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* Past runs (collapsed view) */}
      {runs && runs.length > 1 && (
        <details className="rounded-md border border-[var(--geyser)] bg-white p-2 text-xs">
          <summary className="cursor-pointer font-medium text-[var(--pickled-bluewood)]">
            {runs.length - 1} earlier run{runs.length - 1 === 1 ? "" : "s"}
          </summary>
          <ul className="mt-2 flex flex-col gap-1">
            {runs.slice(1).map((r) => (
              <li
                key={r.id}
                className="flex items-center justify-between gap-2 px-1"
              >
                <span className={statusChipClass(r.status)}>{r.status}</span>
                <span className="flex-1 text-[var(--slate)]">
                  {fmtTimestamp(r.finished_at ?? r.started_at)}
                </span>
                <span className="text-[var(--heather)]">
                  {r.cluster_count} clusters
                </span>
              </li>
            ))}
          </ul>
        </details>
      )}

      {selectedClusterId !== null && latest && (
        <DataQualityClusterModal
          projectId={projectId}
          datasetId={datasetId}
          runId={latest.id}
          clusterId={selectedClusterId}
          sheetA={latest.sheet_a}
          sheetB={latest.sheet_b}
          onClose={() => setSelectedClusterId(null)}
        />
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-[var(--heather)]">
        {label}
      </div>
      <div className="text-sm font-medium text-[var(--pickled-bluewood)]">
        {value}
      </div>
    </div>
  );
}

function CanonicalKeyCell({
  value,
}: {
  value: Record<string, string | number | null>;
}) {
  const entries = Object.entries(value);
  if (entries.length === 0) return <span className="text-[var(--heather)]">—</span>;
  return (
    <span className="flex flex-wrap gap-1.5">
      {entries.map(([k, v]) => (
        <span
          key={k}
          className="inline-flex items-center gap-1 rounded-full border border-[var(--geyser)] bg-[var(--fog)] px-1.5 py-0.5 text-[10px]"
          title={`${k}: ${v ?? "(null)"}`}
        >
          <span className="text-[var(--slate)]">{k}:</span>
          <span className="font-mono">{v == null ? "—" : String(v)}</span>
        </span>
      ))}
    </span>
  );
}
