"use client";

import {
  Activity,
  Check,
  FileText,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent } from "react";

import { api, ApiError, type DqColumnProfile, type DqIssue } from "@/lib/api";
import { cn } from "@/lib/utils";

import PlotlyChart from "./PlotlyChart";

const RAG_COLOURS: Record<string, string> = {
  green: "var(--jade)",
  amber: "var(--marigold)",
  red: "var(--watermelon)",
};

function ragBadgeClass(rag: string): string {
  return cn(
    "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
    rag === "red" && "bg-[var(--watermelon)] text-white",
    rag === "amber" && "bg-[var(--marigold)] text-[var(--pickled-bluewood)]",
    rag === "green" && "bg-[var(--jade)] text-white",
  );
}

export default function DataQualityColumnDrawer({
  projectId,
  datasetId,
  sheetName,
  column,
  issues,
  onClose,
  onBoundsChanged,
  onAnnotated,
}: {
  projectId: number;
  datasetId: number;
  sheetName: string;
  column: DqColumnProfile;
  issues: DqIssue[];
  onClose: () => void;
  onBoundsChanged: () => void;
  onAnnotated: () => void;
}) {
  const [rangeMin, setRangeMin] = useState<string>(
    column.range_min !== null ? String(column.range_min) : "",
  );
  const [rangeMax, setRangeMax] = useState<string>(
    column.range_max !== null ? String(column.range_max) : "",
  );
  const [saving, setSaving] = useState(false);
  const [annotating, setAnnotating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Reset bounds inputs when a different column is opened
  useEffect(() => {
    setRangeMin(column.range_min !== null ? String(column.range_min) : "");
    setRangeMax(column.range_max !== null ? String(column.range_max) : "");
    setError(null);
  }, [column.id, column.range_min, column.range_max]);

  const isNumeric =
    column.semantic_type === "integer" || column.semantic_type === "float";
  const isDate = column.semantic_type === "date";

  async function saveBounds(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    const min = rangeMin.trim() === "" ? null : Number(rangeMin);
    const max = rangeMax.trim() === "" ? null : Number(rangeMax);
    if ((min !== null && Number.isNaN(min)) || (max !== null && Number.isNaN(max))) {
      setError("Bounds must be numbers (or empty).");
      setSaving(false);
      return;
    }
    if (min !== null && max !== null && min > max) {
      setError("Min must be less than or equal to Max.");
      setSaving(false);
      return;
    }
    try {
      await api.setColumnBounds(
        projectId,
        datasetId,
        sheetName,
        column.name,
        { range_min: min, range_max: max },
      );
      onBoundsChanged();
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : "Failed to save bounds");
    } finally {
      setSaving(false);
    }
  }

  async function handleAnnotate() {
    setAnnotating(true);
    setError(null);
    try {
      await api.annotateDataset(projectId, datasetId);
      onAnnotated();
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : "AI annotation failed");
    } finally {
      setAnnotating(false);
    }
  }

  const chart = useMemo(() => buildDistributionChart(column, isNumeric, isDate), [
    column,
    isNumeric,
    isDate,
  ]);

  return (
    <aside
      role="dialog"
      aria-label={`Column ${column.name} details`}
      className="fixed right-0 top-0 z-40 flex h-screen w-full max-w-[28rem] flex-col overflow-y-auto border-l border-[var(--geyser)] bg-white shadow-2xl sm:max-w-[32rem]"
    >
      <header className="flex items-start justify-between gap-2 border-b border-[var(--geyser)] px-4 py-3">
        <div className="flex min-w-0 flex-col gap-1">
          <div className="flex items-center gap-2">
            <span
              className="rounded-full border border-[var(--geyser)] bg-[var(--fog)] px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-[var(--slate)]"
              title={`Inferred dtype: ${column.inferred_dtype}`}
            >
              {column.semantic_type}
            </span>
            <span className={ragBadgeClass(column.rag)}>{column.rag}</span>
          </div>
          <h3 className="m-0 truncate text-base font-semibold text-[var(--pickled-bluewood)]">
            {column.name}
          </h3>
          <span className="text-xs text-[var(--slate)]">
            {sheetName} · column {column.ordinal + 1}
          </span>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close column details"
          className="grid h-7 w-7 place-items-center rounded-md bg-transparent text-[var(--slate)] hover:bg-[var(--fog)] hover:text-[var(--pickled-bluewood)]"
        >
          <X className="h-4 w-4" />
        </button>
      </header>

      <div className="flex flex-col gap-5 p-4">
        <section
          aria-label="Distribution"
          className="rounded-lg border border-[var(--geyser)] bg-white p-3"
        >
          <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-[var(--slate)]">
            <Activity className="h-3.5 w-3.5" />
            Distribution
          </div>
          <PlotlyChart
            data={chart.data}
            layout={chart.layout}
            className="h-48 w-full"
            ariaLabel={`Distribution chart for column ${column.name}`}
          />
        </section>

        <section
          aria-label="Profile metrics"
          className="grid grid-cols-2 gap-2 text-xs"
        >
          <MetricCard label="Null %" value={`${column.null_pct.toFixed(1)}%`} />
          <MetricCard
            label="Distinct"
            value={`${column.distinct_count} (${column.distinct_pct.toFixed(1)}%)`}
          />
          {isNumeric && (
            <>
              <MetricCard
                label="Min"
                value={column.numeric_min !== null ? String(column.numeric_min) : "—"}
              />
              <MetricCard
                label="Max"
                value={column.numeric_max !== null ? String(column.numeric_max) : "—"}
              />
              <MetricCard
                label="Mean"
                value={column.numeric_mean !== null ? column.numeric_mean.toFixed(2) : "—"}
              />
              <MetricCard
                label="Median"
                value={
                  column.numeric_median !== null ? column.numeric_median.toFixed(2) : "—"
                }
              />
              <MetricCard
                label="Outliers (IQR / MAD)"
                value={`${column.outlier_iqr_count ?? "—"} / ${column.outlier_mad_count ?? "—"}`}
              />
              <MetricCard
                label="Type mismatches"
                value={String(column.type_mismatch_count)}
              />
            </>
          )}
          {isDate && (
            <>
              <MetricCard label="Earliest" value={column.date_min ?? "—"} />
              <MetricCard label="Latest" value={column.date_max ?? "—"} />
            </>
          )}
          {column.pattern_label && (
            <MetricCard
              label="Pattern"
              value={`${column.pattern_label} (${(column.pattern_conformance_pct ?? 0).toFixed(0)}%)`}
            />
          )}
        </section>

        {isNumeric && (
          <section
            aria-label="Range bounds"
            className="rounded-lg border border-[var(--geyser)] bg-white p-3"
          >
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--slate)]">
              Range bounds
            </div>
            <form onSubmit={saveBounds} className="!mt-0">
              <div className="grid grid-cols-2 gap-2">
                <label className="flex flex-col gap-1 text-xs">
                  Min
                  <input
                    value={rangeMin}
                    onChange={(e) => setRangeMin(e.target.value)}
                    placeholder="—"
                    aria-label="Range min"
                    className="rounded border border-[var(--geyser)] bg-white px-2 py-1 text-sm text-[var(--pickled-bluewood)] focus:border-[var(--cerulean)] focus:outline-none"
                    inputMode="decimal"
                  />
                </label>
                <label className="flex flex-col gap-1 text-xs">
                  Max
                  <input
                    value={rangeMax}
                    onChange={(e) => setRangeMax(e.target.value)}
                    placeholder="—"
                    aria-label="Range max"
                    className="rounded border border-[var(--geyser)] bg-white px-2 py-1 text-sm text-[var(--pickled-bluewood)] focus:border-[var(--cerulean)] focus:outline-none"
                    inputMode="decimal"
                  />
                </label>
              </div>
              <p className="mt-2 text-[11px] text-[var(--heather)]">
                Setting bounds re-profiles the dataset; any value outside
                [Min, Max] becomes a high-severity validity issue.
              </p>
              <div className="form-actions !mt-3">
                <button type="submit" disabled={saving}>
                  {saving ? "Saving..." : "Save bounds"}
                </button>
                {(column.range_min !== null || column.range_max !== null) && (
                  <button
                    type="button"
                    className="link-button"
                    onClick={async () => {
                      setRangeMin("");
                      setRangeMax("");
                      try {
                        setSaving(true);
                        await api.setColumnBounds(
                          projectId,
                          datasetId,
                          sheetName,
                          column.name,
                          { range_min: null, range_max: null },
                        );
                        onBoundsChanged();
                      } catch (e: unknown) {
                        setError(
                          e instanceof ApiError ? e.message : "Failed to clear",
                        );
                      } finally {
                        setSaving(false);
                      }
                    }}
                    disabled={saving}
                  >
                    Clear bounds
                  </button>
                )}
              </div>
            </form>
          </section>
        )}

        {column.top_values.length > 0 && (
          <section aria-label="Sample values" className="rounded-lg border border-[var(--geyser)] bg-white p-3">
            <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-[var(--slate)]">
              <FileText className="h-3.5 w-3.5" />
              Top values
            </div>
            <ul className="flex flex-col gap-1">
              {column.top_values.slice(0, 10).map((tv) => (
                <li
                  key={tv.value}
                  className="flex items-center justify-between gap-2 text-xs"
                >
                  <span
                    className="truncate text-[var(--pickled-bluewood)]"
                    title={tv.value}
                  >
                    {tv.value}
                  </span>
                  <span className="rounded bg-[var(--fog)] px-1.5 py-0.5 text-[10px] text-[var(--slate)]">
                    {tv.count}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        )}

        <section aria-label="Column issues">
          <div className="mb-2 flex items-center justify-between gap-2">
            <span className="text-xs font-semibold uppercase tracking-wide text-[var(--slate)]">
              Issues ({issues.length})
            </span>
            <button
              type="button"
              onClick={handleAnnotate}
              disabled={annotating}
              className="inline-flex items-center gap-1 rounded-md border border-[var(--geyser)] bg-white px-2 py-0.5 text-[11px] font-medium text-[var(--pickled-bluewood)] transition-colors hover:border-[var(--coral)] hover:text-[var(--coral)] disabled:opacity-50"
              title="Re-run the AI annotator over all issues in this dataset"
            >
              <Sparkles className="h-3 w-3" />
              {annotating ? "Annotating..." : "Re-run AI"}
            </button>
          </div>
          {issues.length === 0 ? (
            <p className="text-xs text-[var(--heather)]">
              No issues recorded for this column.
            </p>
          ) : (
            <ul className="flex flex-col gap-2">
              {issues.map((iss) => (
                <li
                  key={iss.id}
                  className="rounded-md border border-[var(--geyser)] bg-white p-2.5 text-xs"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span
                      className={cn(
                        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
                        iss.severity === "critical" && "bg-[var(--watermelon)] text-white",
                        iss.severity === "high" && "bg-[var(--watermelon)]/80 text-white",
                        iss.severity === "medium" && "bg-[var(--marigold)] text-[var(--pickled-bluewood)]",
                        iss.severity === "low" && "bg-[var(--fog)] text-[var(--slate)]",
                      )}
                    >
                      {iss.severity}
                    </span>
                    <span className="text-[10px] uppercase tracking-wide text-[var(--slate)]">
                      {iss.dimension}
                    </span>
                  </div>
                  <p className="mt-1.5 text-[var(--pickled-bluewood)]">
                    {iss.description}
                  </p>
                  {iss.sample_values.length > 0 && (
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {iss.sample_values.slice(0, 8).map((v, i) => (
                        <span
                          key={`${iss.id}-${i}-${v}`}
                          className="inline-block rounded bg-[var(--fog)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--slate)]"
                        >
                          {v}
                        </span>
                      ))}
                    </div>
                  )}
                  {iss.ai_narrative && (
                    <div className="mt-2 rounded border border-dashed border-[var(--cerulean)]/40 bg-[var(--forget-me-not)]/40 p-2">
                      <div className="mb-0.5 flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wide text-[var(--cerulean)]">
                        <Sparkles className="h-3 w-3" />
                        AI narrative
                      </div>
                      <p className="text-[var(--pickled-bluewood)]">
                        {iss.ai_narrative}
                      </p>
                      {iss.ai_fix && (
                        <p className="mt-1 text-[var(--slate)]">
                          <strong>Suggested fix:</strong> {iss.ai_fix}
                        </p>
                      )}
                    </div>
                  )}
                  {iss.ai_status === "failed" && (
                    <p className="mt-1 text-[10px] italic text-[var(--watermelon)]">
                      AI annotation failed for this issue.
                    </p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>

        {error && (
          <div
            role="alert"
            className="rounded-md border border-[var(--watermelon)] bg-white px-3 py-2 text-xs text-[var(--watermelon)]"
          >
            {error}
          </div>
        )}
      </div>
    </aside>
  );
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-[var(--geyser)] bg-white p-2">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-[var(--slate)]">
        {label}
      </div>
      <div className="mt-0.5 truncate text-sm text-[var(--pickled-bluewood)]">
        {value}
      </div>
    </div>
  );
}

function buildDistributionChart(
  column: DqColumnProfile,
  isNumeric: boolean,
  isDate: boolean,
): { data: import("plotly.js").Data[]; layout: Partial<import("plotly.js").Layout> } {
  if (isNumeric) {
    // We only have summary stats here (not the raw values), so render a
    // box-plot-style bar showing min/p25/median/p75/max. Clearer than a
    // synthetic histogram and honest about what we know.
    const min = column.numeric_min;
    const p25 = column.numeric_p25;
    const med = column.numeric_median;
    const p75 = column.numeric_p75;
    const max = column.numeric_max;
    if (min === null || p25 === null || med === null || p75 === null || max === null) {
      return { data: [], layout: {} };
    }
    return {
      data: [
        {
          type: "scatter",
          mode: "markers",
          x: [min, p25, med, p75, max],
          y: [1, 1, 1, 1, 1],
          marker: { size: [8, 12, 16, 12, 8], color: RAG_COLOURS[column.rag] },
          text: ["min", "p25", "median", "p75", "max"],
          hovertemplate: "%{text}: %{x}<extra></extra>",
        },
      ],
      layout: {
        xaxis: { showgrid: true, gridcolor: "#dde4ec" },
        yaxis: { visible: false, range: [0, 2] },
        showlegend: false,
      },
    };
  }

  if (isDate) {
    if (!column.date_min || !column.date_max) return { data: [], layout: {} };
    return {
      data: [
        {
          type: "scatter",
          mode: "text+markers",
          x: [column.date_min, column.date_max],
          y: [1, 1],
          marker: { size: 10, color: RAG_COLOURS[column.rag] },
          text: ["earliest", "latest"],
          textposition: "top center",
        },
      ],
      layout: {
        xaxis: { type: "date" },
        yaxis: { visible: false, range: [0, 2] },
        showlegend: false,
      },
    };
  }

  // String / fallback: top-values bar chart
  const top = column.top_values.slice(0, 10);
  if (top.length === 0) return { data: [], layout: {} };
  return {
    data: [
      {
        type: "bar",
        x: top.map((t) => t.count),
        y: top.map((t) => t.value),
        orientation: "h",
        marker: { color: RAG_COLOURS[column.rag] },
      },
    ],
    layout: {
      xaxis: { showgrid: true, gridcolor: "#dde4ec" },
      yaxis: { automargin: true, autorange: "reversed" },
    },
  };
}
