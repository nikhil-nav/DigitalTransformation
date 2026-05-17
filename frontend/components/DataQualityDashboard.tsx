"use client";

import {
  AlertTriangle,
  CheckCircle2,
  Database,
  FileSpreadsheet,
  Layers,
  Loader2,
  RefreshCw,
  Sparkles,
  Users,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  api,
  ApiError,
  type DqColumnProfile,
  type DqFunctionalDependency,
  type DqIssue,
  type DqRag,
  type DqRelationship,
  type DqSheetProfile,
} from "@/lib/api";
import { cn } from "@/lib/utils";

import DataQualityColumnDrawer from "./DataQualityColumnDrawer";
import DataQualityCrossTable from "./DataQualityCrossTable";
import DataQualitySimilarityTab from "./DataQualitySimilarityTab";
import PlotlyChart from "./PlotlyChart";

const RAG_RANK: Record<DqRag, number> = { red: 0, amber: 1, green: 2 };

function worstRag(rags: DqRag[]): DqRag {
  if (rags.length === 0) return "green";
  let worst: DqRag = "green";
  for (const r of rags) if (RAG_RANK[r] < RAG_RANK[worst]) worst = r;
  return worst;
}

function ragChipClass(rag: DqRag): string {
  return cn(
    "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
    rag === "red" && "bg-[var(--watermelon)] text-white",
    rag === "amber" && "bg-[var(--marigold)] text-[var(--pickled-bluewood)]",
    rag === "green" && "bg-[var(--jade)] text-white",
  );
}

type SortKey =
  | "name"
  | "type"
  | "null_pct"
  | "distinct"
  | "rag"
  | "issues";

type SortDir = "asc" | "desc";

export default function DataQualityDashboard({
  projectId,
  datasetId,
  onEditSimilarityConfig,
  initialView = "sheet",
}: {
  projectId: number;
  datasetId: number;
  // Optional callback so the parent (DataQualitySection) can re-mount the
  // Profiling Setup page without us having to know about its state.
  // Defaults to a no-op so the dashboard remains useful in isolation.
  onEditSimilarityConfig?: () => void;
  // Which tab to open on first mount. The parent passes "similarity" after
  // the user finishes an Edit-config round trip, so the dashboard re-mounts
  // back on the tab the user was on rather than dropping them on Sheets.
  initialView?: "sheet" | "cross" | "similarity";
}) {
  const [sheets, setSheets] = useState<DqSheetProfile[] | null>(null);
  const [issues, setIssues] = useState<DqIssue[]>([]);
  const [fds, setFds] = useState<DqFunctionalDependency[]>([]);
  const [relationships, setRelationships] = useState<DqRelationship[]>([]);
  const [activeSheetIdx, setActiveSheetIdx] = useState(0);
  const [view, setView] = useState<"sheet" | "cross" | "similarity">(initialView);
  const [sortKey, setSortKey] = useState<SortKey>("rag");
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const [drawerColumn, setDrawerColumn] = useState<DqColumnProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [recomputing, setRecomputing] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [s, i, f, r] = await Promise.all([
        api.getDatasetProfile(projectId, datasetId),
        api.listDatasetIssues(projectId, datasetId),
        api.listFunctionalDependencies(projectId, datasetId),
        api.listRelationships(projectId, datasetId),
      ]);
      setSheets(s);
      setIssues(i);
      setFds(f);
      setRelationships(r);
      if (s.length === 0) setActiveSheetIdx(0);
      else if (activeSheetIdx >= s.length) setActiveSheetIdx(0);
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : "Failed to load profile");
    } finally {
      setLoading(false);
    }
  }, [projectId, datasetId, activeSheetIdx]);

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, datasetId]);

  const activeSheet: DqSheetProfile | null = useMemo(() => {
    if (!sheets || sheets.length === 0) return null;
    return sheets[Math.min(activeSheetIdx, sheets.length - 1)];
  }, [sheets, activeSheetIdx]);

  const issuesByColumn = useMemo(() => {
    const m = new Map<string, DqIssue[]>();
    for (const iss of issues) {
      const k = `${iss.sheet_name}::${iss.column_name ?? ""}`;
      const list = m.get(k);
      if (list) list.push(iss);
      else m.set(k, [iss]);
    }
    return m;
  }, [issues]);

  const fkViolations = useMemo(
    () => issues.filter((i) => i.description.includes("[FK violation]")),
    [issues],
  );

  const totals = useMemo(() => {
    if (!sheets) return { rows: 0, cols: 0, completeness: 0, rag: "green" as DqRag };
    const rows = sheets.reduce((acc, s) => acc + s.row_count, 0);
    const cols = sheets.reduce((acc, s) => acc + s.column_count, 0);
    const completeness =
      sheets.length > 0
        ? sheets.reduce((acc, s) => acc + s.completeness_pct, 0) / sheets.length
        : 0;
    return { rows, cols, completeness, rag: worstRag(sheets.map((s) => s.rag)) };
  }, [sheets]);

  const sheetIssues = useMemo(
    () =>
      activeSheet
        ? issues.filter((i) => i.sheet_name === activeSheet.sheet_name)
        : [],
    [issues, activeSheet],
  );

  const sortedColumns = useMemo(() => {
    if (!activeSheet) return [];
    const issueCountFor = (c: DqColumnProfile) =>
      issuesByColumn.get(`${activeSheet.sheet_name}::${c.name}`)?.length ?? 0;
    const arr = [...activeSheet.columns];
    arr.sort((a, b) => {
      let cmp = 0;
      switch (sortKey) {
        case "name":
          cmp = a.name.localeCompare(b.name);
          break;
        case "type":
          cmp = a.semantic_type.localeCompare(b.semantic_type);
          break;
        case "null_pct":
          cmp = a.null_pct - b.null_pct;
          break;
        case "distinct":
          cmp = a.distinct_count - b.distinct_count;
          break;
        case "rag":
          cmp = RAG_RANK[a.rag] - RAG_RANK[b.rag];
          break;
        case "issues":
          cmp = issueCountFor(a) - issueCountFor(b);
          break;
      }
      return sortDir === "asc" ? cmp : -cmp;
    });
    return arr;
  }, [activeSheet, sortKey, sortDir, issuesByColumn]);

  function toggleSort(k: SortKey) {
    if (sortKey === k) setSortDir(sortDir === "asc" ? "desc" : "asc");
    else {
      setSortKey(k);
      setSortDir(k === "rag" ? "asc" : "desc");
    }
  }

  async function handleRecompute() {
    setRecomputing(true);
    try {
      await api.recomputeProfile(projectId, datasetId);
      await load();
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : "Recompute failed");
    } finally {
      setRecomputing(false);
    }
  }

  if (loading && !sheets) {
    return (
      <div className="flex items-center gap-2 px-4 py-6 text-sm text-[var(--slate)]">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading profile...
      </div>
    );
  }
  if (error) {
    return (
      <div role="alert" className="mx-4 my-4 rounded-md border border-[var(--watermelon)] bg-white px-3 py-2 text-sm text-[var(--watermelon)]">
        {error}
      </div>
    );
  }
  if (!sheets || sheets.length === 0) {
    return (
      <p className="px-4 py-4 text-sm text-[var(--heather)]">
        Profile not available for this dataset yet.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-4 px-4 pb-4">
      {/* KPI strip */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <KpiCard
          icon={<Database className="h-4 w-4" />}
          label="Total rows"
          value={totals.rows.toLocaleString()}
        />
        <KpiCard
          icon={<Layers className="h-4 w-4" />}
          label="Total columns"
          value={String(totals.cols)}
        />
        <KpiCard
          icon={<CheckCircle2 className="h-4 w-4" />}
          label="Completeness"
          value={`${totals.completeness.toFixed(1)}%`}
        />
        <KpiCard
          icon={<AlertTriangle className="h-4 w-4" />}
          label="Overall RAG"
          value={totals.rag.toUpperCase()}
          accent={totals.rag}
        />
      </div>

      {/* Toolbar: view toggle + recompute */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="inline-flex rounded-md border border-[var(--geyser)] bg-white p-0.5">
          <ViewButton
            active={view === "sheet"}
            onClick={() => setView("sheet")}
            label="Sheets"
            icon={<FileSpreadsheet className="h-3.5 w-3.5" />}
          />
          <ViewButton
            active={view === "cross"}
            onClick={() => setView("cross")}
            label="Cross-table"
            icon={<Sparkles className="h-3.5 w-3.5" />}
          />
          <ViewButton
            active={view === "similarity"}
            onClick={() => setView("similarity")}
            label="Similarity"
            icon={<Users className="h-3.5 w-3.5" />}
          />
        </div>
        <button
          type="button"
          onClick={handleRecompute}
          disabled={recomputing}
          className="inline-flex items-center gap-1.5 rounded-md border border-[var(--geyser)] bg-white px-2.5 py-1 text-xs font-medium text-[var(--pickled-bluewood)] transition-colors hover:border-[var(--coral)] hover:text-[var(--coral)] disabled:opacity-50"
          title="Re-profile the dataset; preserves user-set bounds and relationship decisions"
        >
          {recomputing ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <RefreshCw className="h-3.5 w-3.5" />
          )}
          {recomputing ? "Recomputing..." : "Recompute"}
        </button>
      </div>

      {view === "sheet" && (
        <>
          {/* Sheet tabs */}
          <div className="flex flex-wrap items-center gap-1.5 border-b border-[var(--geyser)] pb-1">
            {sheets.map((s, idx) => (
              <button
                key={s.id}
                type="button"
                onClick={() => setActiveSheetIdx(idx)}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-t-md border border-b-0 bg-transparent px-3 py-1.5 text-sm font-medium transition-colors",
                  idx === activeSheetIdx
                    ? "border-[var(--geyser)] bg-white text-[var(--pickled-bluewood)]"
                    : "border-transparent text-[var(--slate)] hover:text-[var(--pickled-bluewood)]",
                )}
                aria-pressed={idx === activeSheetIdx}
              >
                {s.sheet_name}
                <span className={ragChipClass(s.rag)}>{s.rag}</span>
              </button>
            ))}
          </div>

          {activeSheet && (
            <SheetPanel
              sheet={activeSheet}
              issues={sheetIssues}
              sortedColumns={sortedColumns}
              sortKey={sortKey}
              sortDir={sortDir}
              onToggleSort={toggleSort}
              onSelectColumn={setDrawerColumn}
              issuesByColumn={issuesByColumn}
            />
          )}
        </>
      )}

      {view === "cross" && (
        <DataQualityCrossTable
          projectId={projectId}
          datasetId={datasetId}
          functionalDependencies={fds}
          relationships={relationships}
          fkViolations={fkViolations}
          onChange={load}
        />
      )}

      {view === "similarity" && (
        <DataQualitySimilarityTab
          projectId={projectId}
          datasetId={datasetId}
          onEditConfig={onEditSimilarityConfig ?? (() => {})}
        />
      )}

      {drawerColumn && activeSheet && (
        <DataQualityColumnDrawer
          projectId={projectId}
          datasetId={datasetId}
          sheetName={activeSheet.sheet_name}
          column={drawerColumn}
          issues={
            issuesByColumn.get(
              `${activeSheet.sheet_name}::${drawerColumn.name}`,
            ) ?? []
          }
          onClose={() => setDrawerColumn(null)}
          onBoundsChanged={async () => {
            await load();
          }}
          onAnnotated={async () => {
            await load();
          }}
        />
      )}
    </div>
  );
}

// ---------- subcomponents ----------

function SheetPanel({
  sheet,
  issues,
  sortedColumns,
  sortKey,
  sortDir,
  onToggleSort,
  onSelectColumn,
  issuesByColumn,
}: {
  sheet: DqSheetProfile;
  issues: DqIssue[];
  sortedColumns: DqColumnProfile[];
  sortKey: SortKey;
  sortDir: SortDir;
  onToggleSort: (k: SortKey) => void;
  onSelectColumn: (c: DqColumnProfile) => void;
  issuesByColumn: Map<string, DqIssue[]>;
}) {
  const severityCounts = useMemo(() => {
    const counts = { critical: 0, high: 0, medium: 0, low: 0 };
    for (const iss of issues) counts[iss.severity] += 1;
    return counts;
  }, [issues]);

  const donutData: import("plotly.js").Data[] = [
    {
      type: "pie",
      labels: ["Complete", "Missing"],
      values: [sheet.completeness_pct, 100 - sheet.completeness_pct],
      hole: 0.65,
      marker: { colors: ["#00bda5", "#dfe3eb"] },
      textinfo: "none",
      hoverinfo: "label+percent",
      sort: false,
    },
  ];

  const sevData: import("plotly.js").Data[] = [
    {
      type: "bar",
      x: ["critical", "high", "medium", "low"],
      y: [
        severityCounts.critical,
        severityCounts.high,
        severityCounts.medium,
        severityCounts.low,
      ],
      marker: {
        color: ["#7a1f25", "#f2545b", "#f5c26b", "#7c98b6"],
      },
    },
  ];

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div className="rounded-lg border border-[var(--geyser)] bg-white p-3">
          <div className="mb-2 flex items-center justify-between gap-2">
            <span className="text-xs font-semibold uppercase tracking-wide text-[var(--slate)]">
              Completeness
            </span>
            <span className="text-xs text-[var(--slate)]">
              {sheet.row_count.toLocaleString()} rows · {sheet.column_count} cols
            </span>
          </div>
          <PlotlyChart
            data={donutData}
            layout={{
              showlegend: false,
              annotations: [
                {
                  text: `${sheet.completeness_pct.toFixed(1)}%`,
                  font: { size: 18, color: "#33475b" },
                  showarrow: false,
                },
              ],
            }}
            className="h-40 w-full"
            ariaLabel={`Completeness donut for sheet ${sheet.sheet_name}`}
          />
        </div>
        <div className="rounded-lg border border-[var(--geyser)] bg-white p-3">
          <div className="mb-2 flex items-center justify-between gap-2">
            <span className="text-xs font-semibold uppercase tracking-wide text-[var(--slate)]">
              Issues by severity
            </span>
            <span className="text-xs text-[var(--slate)]">
              {issues.length} total
            </span>
          </div>
          <PlotlyChart
            data={sevData}
            layout={{
              xaxis: { showgrid: false },
              yaxis: { showgrid: true, gridcolor: "#eaf0f6", tickformat: "d" },
              showlegend: false,
            }}
            className="h-40 w-full"
            ariaLabel={`Issue severity bar chart for sheet ${sheet.sheet_name}`}
          />
        </div>
      </div>

      {sheet.exact_duplicate_row_count > 0 && (
        <div className="rounded-md border border-[var(--marigold)] bg-white px-3 py-2 text-xs text-[var(--pickled-bluewood)]">
          <strong>{sheet.exact_duplicate_row_count}</strong> rows appear more
          than once on this sheet.
        </div>
      )}

      <div className="overflow-x-auto rounded-lg border border-[var(--geyser)] bg-white">
        <table className="w-full text-left text-xs" aria-label="Column profiles">
          <thead className="bg-[var(--fog)] text-[var(--slate)]">
            <tr>
              <SortHeader
                label="Column"
                k="name"
                sortKey={sortKey}
                sortDir={sortDir}
                onClick={() => onToggleSort("name")}
              />
              <SortHeader
                label="Type"
                k="type"
                sortKey={sortKey}
                sortDir={sortDir}
                onClick={() => onToggleSort("type")}
              />
              <SortHeader
                label="Null %"
                k="null_pct"
                sortKey={sortKey}
                sortDir={sortDir}
                onClick={() => onToggleSort("null_pct")}
                numeric
              />
              <SortHeader
                label="Distinct"
                k="distinct"
                sortKey={sortKey}
                sortDir={sortDir}
                onClick={() => onToggleSort("distinct")}
                numeric
              />
              <SortHeader
                label="RAG"
                k="rag"
                sortKey={sortKey}
                sortDir={sortDir}
                onClick={() => onToggleSort("rag")}
              />
              <SortHeader
                label="Issues"
                k="issues"
                sortKey={sortKey}
                sortDir={sortDir}
                onClick={() => onToggleSort("issues")}
                numeric
              />
            </tr>
          </thead>
          <tbody>
            {sortedColumns.map((c) => {
              const issueCount =
                issuesByColumn.get(`${sheet.sheet_name}::${c.name}`)?.length ?? 0;
              return (
                <tr
                  key={c.id}
                  className="cursor-pointer border-t border-[var(--geyser)] hover:bg-[var(--forget-me-not)]/40"
                  onClick={() => onSelectColumn(c)}
                >
                  <td className="px-3 py-1.5 font-medium text-[var(--pickled-bluewood)]">
                    {c.name}
                  </td>
                  <td className="px-3 py-1.5 text-[var(--slate)]">
                    {c.semantic_type}
                    {c.pattern_label ? ` · ${c.pattern_label}` : ""}
                  </td>
                  <td className="px-3 py-1.5 text-right text-[var(--pickled-bluewood)]">
                    {c.null_pct.toFixed(1)}
                  </td>
                  <td className="px-3 py-1.5 text-right text-[var(--pickled-bluewood)]">
                    {c.distinct_count}
                  </td>
                  <td className="px-3 py-1.5">
                    <span className={ragChipClass(c.rag)}>{c.rag}</span>
                  </td>
                  <td className="px-3 py-1.5 text-right text-[var(--pickled-bluewood)]">
                    {issueCount}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SortHeader({
  label,
  k,
  sortKey,
  sortDir,
  onClick,
  numeric,
}: {
  label: string;
  k: SortKey;
  sortKey: SortKey;
  sortDir: SortDir;
  onClick: () => void;
  numeric?: boolean;
}) {
  const isActive = sortKey === k;
  return (
    <th
      scope="col"
      className={cn(
        "cursor-pointer select-none px-3 py-2 text-[10px] font-semibold uppercase tracking-wide",
        numeric && "text-right",
      )}
      onClick={onClick}
      title={`Sort by ${label}`}
    >
      {label}
      {isActive ? (sortDir === "asc" ? " ↑" : " ↓") : ""}
    </th>
  );
}

function KpiCard({
  icon,
  label,
  value,
  accent,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  accent?: DqRag;
}) {
  return (
    <div
      className={cn(
        "flex items-center gap-3 rounded-lg border bg-white px-3 py-2.5",
        accent === "red" && "border-[var(--watermelon)]",
        accent === "amber" && "border-[var(--marigold)]",
        accent === "green" && "border-[var(--jade)]",
        !accent && "border-[var(--geyser)]",
      )}
    >
      <span className="grid h-8 w-8 place-items-center rounded-md bg-[var(--fog)] text-[var(--slate)]">
        {icon}
      </span>
      <div className="flex min-w-0 flex-col">
        <span className="text-[10px] font-semibold uppercase tracking-wide text-[var(--slate)]">
          {label}
        </span>
        <span className="truncate text-base font-semibold text-[var(--pickled-bluewood)]">
          {value}
        </span>
      </div>
    </div>
  );
}

function ViewButton({
  active,
  onClick,
  label,
  icon,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  icon: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "inline-flex items-center gap-1.5 rounded border-0 px-3 py-1 text-sm font-medium transition-colors",
        active
          ? "bg-[var(--coral)] text-white"
          : "bg-transparent text-[var(--slate)] hover:bg-[var(--fog)] hover:text-[var(--pickled-bluewood)]",
      )}
    >
      {icon}
      {label}
    </button>
  );
}
