"use client";

import {
  FileSpreadsheet,
  Loader2,
  Sparkles,
  Trash2,
  Upload,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState, type DragEvent } from "react";

import {
  api,
  ApiError,
  type DataQualityDataset,
} from "@/lib/api";
import { cn } from "@/lib/utils";

import DataQualityChatDrawer from "./DataQualityChatDrawer";
import DataQualityConfigPage from "./DataQualityConfigPage";
import DataQualityDashboard from "./DataQualityDashboard";
import LlmSettings from "./LlmSettings";

const ACCEPT = ".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function fmtTimestamp(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export default function DataQualitySection({
  projectId,
}: {
  projectId: number;
}) {
  const [datasets, setDatasets] = useState<DataQualityDataset[] | null>(null);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [dragging, setDragging] = useState(false);
  // True while the user is in an Edit-config round trip from the
  // Similarity tab — used to land them back on the Similarity tab when
  // the dashboard re-mounts after save/skip, instead of dumping them on
  // the default Sheets tab.
  const [returnToSimilarity, setReturnToSimilarity] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const activeDataset =
    activeId !== null ? datasets?.find((d) => d.id === activeId) ?? null : null;

  const load = useCallback(async () => {
    try {
      const list = await api.listDatasets(projectId);
      setDatasets(list);
      setActiveId((prev) =>
        prev !== null && list.some((d) => d.id === prev)
          ? prev
          : list[0]?.id ?? null,
      );
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : "Failed to load datasets");
    }
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  // One-shot consumer: once the dashboard has re-mounted with
  // initialView="similarity", clear the flag so a later upload of a
  // different dataset doesn't accidentally also default to Similarity.
  useEffect(() => {
    if (returnToSimilarity && activeDataset?.config_completed_at !== null && activeDataset?.config_completed_at !== undefined) {
      setReturnToSimilarity(false);
    }
  }, [returnToSimilarity, activeDataset?.config_completed_at]);

  // Annotation runs as a backend BackgroundTask, so the upload returns
  // 'running' immediately. Poll the dataset list every 5s while any
  // dataset is still 'running' so the AI badge flips to done/failed
  // without the user having to refresh. The interval is cleared as soon
  // as no dataset is in flight, so an idle dashboard makes zero polls.
  const hasRunningAnnotation = (datasets ?? []).some(
    (d) => d.annotation_status === "running",
  );
  useEffect(() => {
    if (!hasRunningAnnotation) return;
    const id = window.setInterval(() => {
      void load();
    }, 5000);
    return () => window.clearInterval(id);
  }, [hasRunningAnnotation, load]);

  async function handleFiles(list: FileList) {
    setUploading(true);
    setError(null);
    try {
      for (const f of Array.from(list)) {
        const row = await api.uploadDataset(projectId, f);
        setDatasets((prev) => (prev ? [row, ...prev] : [row]));
        setActiveId(row.id);
      }
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  async function handleDelete(id: number) {
    setDeletingId(id);
    setError(null);
    try {
      await api.deleteDataset(projectId, id);
      setDatasets((prev) => {
        const next = prev ? prev.filter((d) => d.id !== id) : prev;
        if (id === activeId) {
          setActiveId(next && next[0] ? next[0].id : null);
        }
        return next;
      });
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : "Delete failed");
    } finally {
      setDeletingId(null);
    }
  }

  const dragHandlers = {
    onDragOver: (e: DragEvent) => {
      e.preventDefault();
      setDragging(true);
    },
    onDragLeave: (e: DragEvent) => {
      e.preventDefault();
      setDragging(false);
    },
    onDrop: (e: DragEvent) => {
      e.preventDefault();
      setDragging(false);
      if (e.dataTransfer.files?.length) void handleFiles(e.dataTransfer.files);
    },
  };

  return (
    <section className="card flex flex-col gap-4 !p-0">
      <header className="flex items-center justify-between gap-2 border-b border-[var(--geyser)] px-4 py-3">
        <div className="flex items-center gap-2">
          <FileSpreadsheet className="h-4 w-4 text-[var(--cerulean)]" />
          <h2 className="m-0 text-base font-semibold text-[var(--pickled-bluewood)]">
            Data Quality datasets
          </h2>
        </div>
        {datasets && (
          <span className="text-xs text-[var(--slate)]">
            {datasets.length} dataset{datasets.length === 1 ? "" : "s"}
          </span>
        )}
      </header>

      <div className="px-4">
        <div
          {...dragHandlers}
          className={cn(
            "rounded-lg border border-dashed px-4 py-6 transition-colors",
            dragging
              ? "border-[var(--coral)] bg-[var(--forget-me-not)]"
              : "border-[var(--geyser)] bg-white",
          )}
          aria-label="Upload xlsx dropzone"
        >
          <div className="flex flex-col items-center gap-2 text-center">
            <Upload className="h-5 w-5 text-[var(--slate)]" />
            <p className="m-0 text-sm text-[var(--pickled-bluewood)]">
              Drop an <strong>.xlsx</strong> here, or
            </p>
            <button
              type="button"
              onClick={() => inputRef.current?.click()}
              disabled={uploading}
              className="inline-flex items-center gap-1.5 rounded-md border border-[var(--geyser)] bg-white px-3 py-1 text-xs font-medium text-[var(--pickled-bluewood)] transition-all hover:border-[var(--coral)] hover:text-[var(--coral)] disabled:cursor-not-allowed disabled:opacity-50"
            >
              {uploading ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Upload className="h-3.5 w-3.5" />
              )}
              <span>{uploading ? "Uploading..." : "Choose file"}</span>
            </button>
            <p className="m-0 text-xs text-[var(--heather)]">
              Max 25 MB. Multi-sheet workbooks supported; each sheet is treated
              as a separate table.
            </p>
          </div>
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPT}
            hidden
            onChange={(e) => {
              const list = e.target.files;
              if (list?.length) void handleFiles(list);
              e.target.value = "";
            }}
          />
        </div>
      </div>

      {error && (
        <div
          role="alert"
          className="mx-4 rounded-md border border-[var(--watermelon)] bg-white px-3 py-2 text-sm text-[var(--watermelon)]"
        >
          {error}
        </div>
      )}

      <div className="px-4 pb-4">
        {datasets === null ? (
          <p className="text-sm text-[var(--slate)]">Loading datasets...</p>
        ) : datasets.length === 0 ? (
          <p className="text-sm text-[var(--heather)]">
            No datasets yet. Upload an .xlsx above to get started.
          </p>
        ) : (
          <ul className="flex flex-col gap-2">
            {datasets.map((d) => {
              const isActive = d.id === activeId;
              return (
                <li
                  key={d.id}
                  onClick={() => setActiveId(d.id)}
                  className={cn(
                    "flex cursor-pointer flex-col gap-2 rounded-md border bg-white px-3 py-2.5 transition-colors",
                    isActive
                      ? "border-[var(--coral)]"
                      : "border-[var(--geyser)] hover:border-[var(--cerulean)]",
                  )}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex min-w-0 items-center gap-2">
                      <FileSpreadsheet className="h-4 w-4 shrink-0 text-[var(--slate)]" />
                      <span
                        className="truncate text-sm font-medium text-[var(--pickled-bluewood)]"
                        title={d.original_filename}
                      >
                        {d.original_filename}
                      </span>
                      <span className="text-xs text-[var(--heather)]">
                        {fmtSize(d.size_bytes)}
                      </span>
                      <AnnotationStatusChip dataset={d} />
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="text-xs text-[var(--slate)]">
                        {fmtTimestamp(d.uploaded_at)}
                      </span>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          void handleDelete(d.id);
                        }}
                        disabled={deletingId === d.id}
                        aria-label={`Delete ${d.original_filename}`}
                        title="Delete dataset"
                        className="grid h-7 w-7 place-items-center rounded bg-transparent text-[var(--slate)] hover:bg-[var(--fog)] hover:text-[var(--watermelon)] disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {deletingId === d.id ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <Trash2 className="h-3.5 w-3.5" />
                        )}
                      </button>
                    </div>
                  </div>
                  <ul className="flex flex-wrap gap-1.5">
                    {d.sheets.map((s) => (
                      <li
                        key={s.name}
                        className="inline-flex items-center gap-1.5 rounded-full border border-[var(--geyser)] bg-[var(--fog)] px-2.5 py-0.5 text-xs text-[var(--pickled-bluewood)]"
                        title={`${s.row_count} row${s.row_count === 1 ? "" : "s"} × ${s.column_count} col${s.column_count === 1 ? "" : "s"}`}
                      >
                        <span className="font-medium">{s.name}</span>
                        <span className="text-[var(--slate)]">
                          {s.row_count}×{s.column_count}
                        </span>
                      </li>
                    ))}
                  </ul>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {/* LLM settings: needed for AI annotation + chat. Always visible so a
          user uploading their first dataset can configure their key. */}
      <div className="px-4 pb-2">
        <LlmSettings />
      </div>

      {/* Epic 3: blocking gate. When config_completed_at is NULL the user
          has not yet visited (or skipped) the Profiling Setup page; render
          it instead of the dashboard. The dashboard fan-out (profile,
          issues, FDs, relationships) doesn't start until the gate is
          cleared, so users avoid wasted requests while configuring. */}
      {activeId !== null && activeDataset && activeDataset.config_completed_at === null && (
        <div className="border-t border-[var(--geyser)] pt-4">
          <DataQualityConfigPage
            projectId={projectId}
            datasetId={activeId}
            availableSheets={activeDataset.sheets.map((s) => s.name)}
            onComplete={() => {
              // Patch the dataset locally so we don't re-mount the config
              // page while waiting for the next list refresh.
              const now = new Date().toISOString();
              setDatasets((prev) =>
                prev
                  ? prev.map((d) =>
                      d.id === activeId
                        ? { ...d, config_completed_at: now }
                        : d,
                    )
                  : prev,
              );
            }}
          />
        </div>
      )}

      {/* Dashboard for the active dataset (only after the gate is cleared) */}
      {activeId !== null && activeDataset && activeDataset.config_completed_at !== null && (
        <div className="border-t border-[var(--geyser)] pt-4">
          <DataQualityDashboard
            projectId={projectId}
            datasetId={activeId}
            initialView={returnToSimilarity ? "similarity" : "sheet"}
            onEditSimilarityConfig={() => {
              // Local re-mount of the config page without touching the
              // server-side gate. If the user dismisses without saving,
              // a page refresh would show the dashboard again — that's
              // intentional. Save / skip will re-set the timestamp.
              setReturnToSimilarity(true);
              setDatasets((prev) =>
                prev
                  ? prev.map((d) =>
                      d.id === activeId
                        ? { ...d, config_completed_at: null }
                        : d,
                    )
                  : prev,
              );
            }}
          />
        </div>
      )}

      {/* Chat drawer is mounted (closed) whenever a dataset is selected so
          its floating opener button is available across the dashboard. */}
      {activeId !== null && activeDataset && activeDataset.config_completed_at !== null && (
        <DataQualityChatDrawer projectId={projectId} datasetId={activeId} />
      )}
    </section>
  );
}

function AnnotationStatusChip({ dataset }: { dataset: DataQualityDataset }) {
  if (dataset.annotation_status === "pending") return null;
  const labels = {
    running: {
      text: "AI running",
      cls: "border-[var(--cerulean)] text-[var(--cerulean)]",
    },
    done: {
      text: "AI done",
      cls: "border-[var(--jade)] text-[var(--jade)]",
    },
    failed: {
      text: "AI failed",
      cls: "border-[var(--watermelon)] text-[var(--watermelon)]",
    },
  } as const;
  const { text, cls } = labels[dataset.annotation_status];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border bg-white px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
        cls,
      )}
      title={dataset.annotation_error ?? undefined}
    >
      <Sparkles className="h-2.5 w-2.5" />
      {text}
    </span>
  );
}
