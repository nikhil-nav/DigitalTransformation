"use client";

import { Check, GitBranch, Link2, X } from "lucide-react";
import { useState } from "react";

import {
  api,
  ApiError,
  type DqFunctionalDependency,
  type DqIssue,
  type DqRelationship,
} from "@/lib/api";
import { cn } from "@/lib/utils";

export default function DataQualityCrossTable({
  projectId,
  datasetId,
  functionalDependencies,
  relationships,
  fkViolations,
  onChange,
}: {
  projectId: number;
  datasetId: number;
  functionalDependencies: DqFunctionalDependency[];
  relationships: DqRelationship[];
  fkViolations: DqIssue[];
  onChange: () => void;
}) {
  const [busyId, setBusyId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function changeStatus(
    rel: DqRelationship,
    status: "confirmed" | "dismissed",
  ) {
    setBusyId(rel.id);
    setError(null);
    try {
      await api.updateRelationshipStatus(projectId, datasetId, rel.id, status);
      onChange();
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : "Failed to update status");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <section aria-label="Suggested relationships">
        <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-[var(--slate)]">
          <Link2 className="h-3.5 w-3.5" />
          Cross-sheet relationships
        </div>
        {relationships.length === 0 ? (
          <p className="text-sm text-[var(--heather)]">
            No relationship suggestions yet. Upload a workbook with shared keys
            across sheets and they will appear here.
          </p>
        ) : (
          <ul className="flex flex-col gap-2">
            {relationships.map((r) => (
              <li
                key={r.id}
                className={cn(
                  "rounded-md border bg-white p-3",
                  r.status === "confirmed"
                    ? "border-[var(--jade)]"
                    : r.status === "dismissed"
                      ? "border-[var(--geyser)] opacity-70"
                      : "border-[var(--geyser)]",
                )}
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex min-w-0 items-center gap-1.5 text-sm text-[var(--pickled-bluewood)]">
                    <span className="font-medium">
                      {r.child_sheet}.{r.child_column}
                    </span>
                    <span className="text-[var(--slate)]">→</span>
                    <span className="font-medium">
                      {r.parent_sheet}.{r.parent_column}
                    </span>
                  </div>
                  <span
                    className={cn(
                      "rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
                      r.status === "confirmed" && "bg-[var(--jade)] text-white",
                      r.status === "dismissed" && "bg-[var(--fog)] text-[var(--slate)]",
                      r.status === "suggested" && "bg-[var(--marigold)] text-[var(--pickled-bluewood)]",
                    )}
                  >
                    {r.status}
                  </span>
                </div>
                <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-[11px] text-[var(--slate)] sm:grid-cols-4">
                  <Signal label="Type match" value={r.type_match ? "yes" : "no"} />
                  <Signal
                    label="Coverage"
                    value={`${(r.subset_coverage * 100).toFixed(0)}%`}
                  />
                  <Signal
                    label="Cardinality"
                    value={r.cardinality.replace("_", "→")}
                  />
                  <Signal
                    label="Name sim"
                    value={`${(r.name_similarity * 100).toFixed(0)}%`}
                  />
                </div>
                <div className="mt-2 flex items-center justify-between gap-2">
                  <span className="text-xs text-[var(--slate)]">
                    Confidence{" "}
                    <strong className="text-[var(--pickled-bluewood)]">
                      {r.confidence_pct.toFixed(0)}%
                    </strong>
                  </span>
                  <div className="flex items-center gap-1.5">
                    <button
                      type="button"
                      onClick={() => changeStatus(r, "confirmed")}
                      disabled={busyId === r.id || r.status === "confirmed"}
                      className="inline-flex items-center gap-1 rounded-md border border-[var(--geyser)] bg-white px-2 py-1 text-xs font-medium text-[var(--pickled-bluewood)] hover:border-[var(--jade)] hover:text-[var(--jade)] disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <Check className="h-3 w-3" />
                      Confirm
                    </button>
                    <button
                      type="button"
                      onClick={() => changeStatus(r, "dismissed")}
                      disabled={busyId === r.id || r.status === "dismissed"}
                      className="inline-flex items-center gap-1 rounded-md border border-[var(--geyser)] bg-white px-2 py-1 text-xs font-medium text-[var(--pickled-bluewood)] hover:border-[var(--watermelon)] hover:text-[var(--watermelon)] disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <X className="h-3 w-3" />
                      Dismiss
                    </button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      {fkViolations.length > 0 && (
        <section aria-label="FK violations">
          <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-[var(--watermelon)]">
            FK violations ({fkViolations.length})
          </div>
          <ul className="flex flex-col gap-1.5">
            {fkViolations.map((v) => (
              <li
                key={v.id}
                className="rounded-md border border-[var(--watermelon)] bg-white p-2.5 text-xs text-[var(--pickled-bluewood)]"
              >
                <p>{v.description}</p>
                {v.sample_values.length > 0 && (
                  <div className="mt-1 flex flex-wrap gap-1">
                    {v.sample_values.slice(0, 8).map((s, i) => (
                      <span
                        key={i}
                        className="inline-block rounded bg-[var(--fog)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--slate)]"
                      >
                        {s}
                      </span>
                    ))}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section aria-label="Functional dependencies">
        <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-[var(--slate)]">
          <GitBranch className="h-3.5 w-3.5" />
          Functional dependencies
        </div>
        {functionalDependencies.length === 0 ? (
          <p className="text-sm text-[var(--heather)]">
            No high-confidence within-sheet dependencies detected.
          </p>
        ) : (
          <ul className="flex flex-col gap-1.5">
            {functionalDependencies.map((fd) => (
              <li
                key={fd.id}
                className="rounded-md border border-[var(--geyser)] bg-white p-2.5 text-xs text-[var(--pickled-bluewood)]"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span>
                    <span className="font-mono text-[11px] text-[var(--slate)]">
                      [{fd.sheet_name}]
                    </span>{" "}
                    <strong>{fd.determinant_column}</strong>{" "}
                    <span className="text-[var(--slate)]">→</span>{" "}
                    <strong>{fd.dependent_column}</strong>
                  </span>
                  <span className="rounded bg-[var(--fog)] px-1.5 py-0.5 text-[10px] text-[var(--slate)]">
                    {fd.confidence_pct.toFixed(0)}%
                  </span>
                </div>
                {fd.counter_example_count > 0 && (
                  <p className="mt-1 text-[10px] text-[var(--slate)]">
                    {fd.counter_example_count} counter-example(s); samples:{" "}
                    {fd.sample_counter_examples.slice(0, 4).join(", ")}
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
          className="rounded-md border border-[var(--watermelon)] bg-white px-3 py-2 text-sm text-[var(--watermelon)]"
        >
          {error}
        </div>
      )}
    </div>
  );
}

function Signal({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-[var(--slate)]">
        {label}
      </div>
      <div className="text-xs font-medium text-[var(--pickled-bluewood)]">
        {value}
      </div>
    </div>
  );
}
