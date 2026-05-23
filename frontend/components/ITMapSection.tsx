"use client";

import {
  AlertTriangle,
  CheckCircle2,
  FileSpreadsheet,
  Loader2,
  Network,
  Play,
  Trash2,
  Upload,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type DragEvent,
} from "react";

import {
  api,
  ApiError,
  type ItMapAgentRun,
  type ItMapInventory,
} from "@/lib/api";
import { cn } from "@/lib/utils";

import ITMapKanban from "./ITMapKanban";

const ACCEPT =
  ".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function fmtTimestamp(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

type InventoryWithRun = ItMapInventory & {
  latest_run: ItMapAgentRun | null;
};

export default function ITMapSection({ projectId }: { projectId: number }) {
  const [items, setItems] = useState<InventoryWithRun[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [runningId, setRunningId] = useState<number | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [dragging, setDragging] = useState(false);
  const [activeInventoryId, setActiveInventoryId] = useState<number | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const list = await api.listItMapInventories(projectId);
      // Per-inventory: fetch the latest run so the status badge stays
      // accurate. Parallel; fine for the dozen-or-so inventories per
      // project this UI is sized for.
      const withRuns: InventoryWithRun[] = await Promise.all(
        list.map(async (inv) => {
          try {
            const runs = await api.listItMapRuns(projectId, inv.id);
            return { ...inv, latest_run: runs[0] ?? null };
          } catch {
            return { ...inv, latest_run: null };
          }
        }),
      );
      setItems(withRuns);
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : "Failed to load inventories");
    }
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  // Mirror the AI-annotation pattern: poll every 5s while ANY inventory
  // has a 'running' run. Auto-stops once all are settled so an idle
  // section makes zero requests.
  const hasRunningAgent = (items ?? []).some(
    (i) => i.latest_run?.status === "running",
  );
  useEffect(() => {
    if (!hasRunningAgent) return;
    const id = window.setInterval(() => {
      void load();
    }, 5000);
    return () => window.clearInterval(id);
  }, [hasRunningAgent, load]);

  async function handleFiles(list: FileList) {
    setUploading(true);
    setError(null);
    try {
      for (const f of Array.from(list)) {
        const inv = await api.uploadItMapInventory(projectId, f);
        setItems((prev) =>
          prev ? [{ ...inv, latest_run: null }, ...prev] : [{ ...inv, latest_run: null }],
        );
      }
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  async function handleRun(id: number) {
    setRunningId(id);
    setError(null);
    try {
      const run = await api.runItMapAgent(projectId, id);
      // Patch locally so the status badge flips to 'running' immediately
      // and the polling effect kicks in without waiting for the next
      // /inventories+/runs round-trip.
      setItems((prev) =>
        prev
          ? prev.map((inv) =>
              inv.id === id ? { ...inv, latest_run: run } : inv,
            )
          : prev,
      );
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : "Run failed");
    } finally {
      setRunningId(null);
    }
  }

  async function handleDelete(id: number) {
    setDeletingId(id);
    setError(null);
    try {
      await api.deleteItMapInventory(projectId, id);
      setItems((prev) => (prev ? prev.filter((i) => i.id !== id) : prev));
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
          <Network className="h-4 w-4 text-[var(--cerulean)]" />
          <h2 className="m-0 text-base font-semibold text-[var(--pickled-bluewood)]">
            IT Map
          </h2>
        </div>
        {items && (
          <span className="text-xs text-[var(--slate)]">
            {items.length} inventor{items.length === 1 ? "y" : "ies"}
          </span>
        )}
      </header>

      {/* Upload dropzone */}
      <div className="px-4">
        <div
          {...dragHandlers}
          className={cn(
            "rounded-lg border border-dashed px-4 py-6 transition-colors",
            dragging
              ? "border-[var(--coral)] bg-[var(--forget-me-not)]"
              : "border-[var(--geyser)] bg-white",
          )}
          aria-label="Upload application inventory dropzone"
        >
          <div className="flex flex-col items-center gap-2 text-center">
            <Upload className="h-5 w-5 text-[var(--slate)]" />
            <p className="m-0 text-sm text-[var(--pickled-bluewood)]">
              Drop an application inventory <strong>.xlsx</strong> here, or
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
              The agent will read your sheet, infer which columns are which,
              and propose L2 capability mappings.
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
        {items === null ? (
          <p className="text-sm text-[var(--slate)]">Loading inventories...</p>
        ) : items.length === 0 ? (
          <p className="text-sm text-[var(--heather)]">
            No inventories yet. Upload an .xlsx above to get started.
          </p>
        ) : (
          <ul className="flex flex-col gap-2">
            {items.map((inv) => (
              <li
                key={inv.id}
                onClick={() => setActiveInventoryId(inv.id)}
                className={cn(
                  "flex cursor-pointer flex-col gap-2 rounded-md border bg-white px-3 py-2.5 transition-colors",
                  activeInventoryId === inv.id
                    ? "border-[var(--coral)]"
                    : "border-[var(--geyser)] hover:border-[var(--cerulean)]",
                )}
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex min-w-0 items-center gap-2">
                    <FileSpreadsheet className="h-4 w-4 shrink-0 text-[var(--slate)]" />
                    <span
                      className="truncate text-sm font-medium text-[var(--pickled-bluewood)]"
                      title={inv.original_filename}
                    >
                      {inv.original_filename}
                    </span>
                    <span className="text-xs text-[var(--heather)]">
                      {fmtSize(inv.size_bytes)}
                    </span>
                    <RunStatusChip run={inv.latest_run} />
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-[var(--slate)]">
                      {fmtTimestamp(inv.uploaded_at)}
                    </span>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        void handleRun(inv.id);
                      }}
                      disabled={
                        runningId === inv.id ||
                        inv.latest_run?.status === "running"
                      }
                      className="inline-flex items-center gap-1 rounded border border-[var(--coral)] bg-white px-2 py-1 text-xs font-medium text-[var(--coral)] hover:bg-[var(--forget-me-not)] disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {runningId === inv.id || inv.latest_run?.status === "running" ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <Play className="h-3 w-3" />
                      )}
                      {inv.latest_run ? "Re-run" : "Run agent"}
                    </button>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        void handleDelete(inv.id);
                      }}
                      disabled={deletingId === inv.id}
                      aria-label={`Delete ${inv.original_filename}`}
                      title="Delete inventory"
                      className="grid h-7 w-7 place-items-center rounded bg-transparent text-[var(--slate)] hover:bg-[var(--fog)] hover:text-[var(--watermelon)] disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {deletingId === inv.id ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Trash2 className="h-3.5 w-3.5" />
                      )}
                    </button>
                  </div>
                </div>
                {/* Sheet chips — primary highlighted */}
                <ul className="flex flex-wrap gap-1.5">
                  {inv.sheets.map((s) => (
                    <li
                      key={s.name}
                      className={cn(
                        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs",
                        s.name === inv.primary_sheet
                          ? "border-[var(--cerulean)] bg-[var(--forget-me-not)] text-[var(--pickled-bluewood)]"
                          : "border-[var(--geyser)] bg-[var(--fog)] text-[var(--slate)]",
                      )}
                      title={
                        s.name === inv.primary_sheet
                          ? `Primary sheet (${s.row_count} rows × ${s.column_count} cols)`
                          : `Ignored: agent processes only the primary sheet (${s.row_count} rows × ${s.column_count} cols)`
                      }
                    >
                      <span className="font-medium">{s.name}</span>
                      <span>
                        {s.row_count}×{s.column_count}
                      </span>
                    </li>
                  ))}
                </ul>
                {inv.latest_run && (
                  <RunSummary run={inv.latest_run} />
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Kanban: shown for the active inventory only when its agent run
          is done. Other states (no run yet, still running, failed)
          surface above on the inventory row itself. */}
      {(() => {
        const active = items?.find((i) => i.id === activeInventoryId);
        if (!active || active.latest_run?.status !== "done") return null;
        return (
          <div className="border-t border-[var(--geyser)] pt-4">
            <ITMapKanban
              projectId={projectId}
              inventoryId={active.id}
            />
          </div>
        );
      })()}
    </section>
  );
}

function RunStatusChip({ run }: { run: ItMapAgentRun | null }) {
  if (!run) return null;
  const map = {
    running: {
      cls: "border-[var(--cerulean)] text-[var(--cerulean)]",
      icon: <Loader2 className="h-2.5 w-2.5 animate-spin" />,
      text: "Agent running",
    },
    done: {
      cls: "border-[var(--jade)] text-[var(--jade)]",
      icon: <CheckCircle2 className="h-2.5 w-2.5" />,
      text: "Mapped",
    },
    failed: {
      cls: "border-[var(--watermelon)] text-[var(--watermelon)]",
      icon: <AlertTriangle className="h-2.5 w-2.5" />,
      text: "Failed",
    },
  } as const;
  const { cls, icon, text } = map[run.status];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border bg-white px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
        cls,
      )}
      title={run.error ?? undefined}
    >
      {icon}
      {text}
    </span>
  );
}

function RunSummary({ run }: { run: ItMapAgentRun }) {
  if (run.status === "failed") {
    return (
      <p className="text-xs text-[var(--watermelon)]">{run.error}</p>
    );
  }
  if (run.status === "running") {
    return (
      <p className="text-xs text-[var(--slate)]">
        Agent is processing the inventory; this page polls every 5s.
      </p>
    );
  }
  return (
    <p className="text-xs text-[var(--slate)]">
      {run.application_count} applications · {run.mapping_count} mappings ·{" "}
      {run.unmappable_count} unmapped · finished{" "}
      {fmtTimestamp(run.finished_at)}
    </p>
  );
}
