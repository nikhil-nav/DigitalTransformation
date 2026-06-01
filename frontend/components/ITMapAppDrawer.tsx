"use client";

import { CheckCircle2, Loader2, Plus, X, XCircle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  api,
  ApiError,
  type Capability,
  type ItMapApplication,
  type ItMapMapping,
} from "@/lib/api";
import { cn } from "@/lib/utils";

export default function ITMapAppDrawer({
  projectId,
  applicationId,
  l2Capabilities,
  onClose,
  onMutated,
}: {
  projectId: number;
  applicationId: number;
  l2Capabilities: Capability[];
  onClose: () => void;
  onMutated: () => void;
}) {
  const [app, setApp] = useState<ItMapApplication | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyMappingId, setBusyMappingId] = useState<number | null>(null);
  const [adding, setAdding] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);

  // Capabilities the user can ADD a mapping to: every L2 the app isn't
  // already mapped to with a non-dismissed mapping. Dismissed mappings
  // don't block re-mapping (they can re-mapping via re-enabling, but the
  // POST endpoint returns 409 for any existing mapping regardless of
  // status — so we ALSO exclude dismissed ones from the picker and tell
  // the user to PATCH them instead).
  const usedCapIds = useMemo(
    () => new Set((app?.mappings ?? []).map((m) => m.capability_id)),
    [app],
  );
  const availableCaps = useMemo(
    () => l2Capabilities.filter((c) => !usedCapIds.has(c.id)),
    [l2Capabilities, usedCapIds],
  );

  async function load() {
    setError(null);
    try {
      const a = await api.getItMapApplication(projectId, applicationId);
      setApp(a);
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : "Failed to load");
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, applicationId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function flip(mappingId: number, status: "confirmed" | "dismissed") {
    setBusyMappingId(mappingId);
    setError(null);
    try {
      await api.updateItMapMappingStatus(projectId, mappingId, status);
      await load();
      onMutated();
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : "Update failed");
    } finally {
      setBusyMappingId(null);
    }
  }

  async function addMapping(capabilityId: number) {
    setAdding(true);
    setError(null);
    try {
      await api.createItMapMapping(projectId, {
        application_id: applicationId,
        capability_id: capabilityId,
      });
      setPickerOpen(false);
      await load();
      onMutated();
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : "Add mapping failed");
    } finally {
      setAdding(false);
    }
  }

  const capName = (id: number): string => {
    const c = l2Capabilities.find((cap) => cap.id === id);
    return c?.name ?? `#${id}`;
  };

  return (
    <div
      role="dialog"
      aria-label="Application detail"
      aria-modal="true"
      className="fixed inset-0 z-40 grid place-items-end bg-black/30"
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="flex h-full w-full max-w-[36rem] flex-col overflow-hidden border-l border-[var(--geyser)] bg-white shadow-xl"
      >
        <header className="flex items-center justify-between gap-2 border-b border-[var(--geyser)] px-4 py-3">
          <div className="min-w-0">
            <h3 className="m-0 truncate text-base font-semibold text-[var(--pickled-bluewood)]">
              {app?.inferred_name ?? "Application"}
            </h3>
            {app && (
              <p className="m-0 text-[10px] text-[var(--slate)]">
                Row {app.row_index} · {app.sheet_name}
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close application drawer"
            className="grid h-7 w-7 place-items-center rounded text-[var(--slate)] hover:bg-[var(--fog)] hover:text-[var(--pickled-bluewood)]"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-4 py-4">
          {error && (
            <p role="alert" className="mb-3 text-sm text-[var(--watermelon)]">
              {error}
            </p>
          )}
          {!app && !error && (
            <div className="flex items-center gap-2 text-sm text-[var(--slate)]">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading...
            </div>
          )}

          {app && (
            <div className="flex flex-col gap-4">
              {/* Inferred fields */}
              <div>
                <h4 className="m-0 mb-1 text-xs font-semibold uppercase tracking-wide text-[var(--slate)]">
                  Inferred
                </h4>
                <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                  <InferredField label="Name" value={app.inferred_name} />
                  <InferredField label="Owner" value={app.inferred_owner} />
                  <InferredField
                    label="Business function"
                    value={app.inferred_business_function}
                  />
                  <InferredField
                    label="Technology"
                    value={app.inferred_technology}
                  />
                  <InferredField
                    label="Criticality"
                    value={app.inferred_criticality}
                  />
                  <InferredField
                    label="Lifecycle"
                    value={app.inferred_lifecycle}
                  />
                </dl>
                {app.inferred_description && (
                  <p className="mt-2 text-xs text-[var(--slate)]">
                    {app.inferred_description}
                  </p>
                )}
                {app.unmappable_reason && (
                  <p className="mt-2 rounded border border-[var(--watermelon)]/40 bg-[var(--watermelon)]/5 p-2 text-xs text-[var(--watermelon)]">
                    Unmappable: {app.unmappable_reason}
                  </p>
                )}
              </div>

              {/* Raw row */}
              <details>
                <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wide text-[var(--slate)]">
                  Raw row
                </summary>
                <table
                  className="mt-2 w-full border-collapse text-xs"
                  aria-label="Raw row"
                >
                  <tbody>
                    {Object.entries(app.raw_row).map(([k, v]) => (
                      <tr key={k} className="border-b border-[var(--geyser)]">
                        <th className="w-1/3 px-1 py-1 text-left font-medium text-[var(--slate)]">
                          {k}
                        </th>
                        <td className="px-1 py-1 text-[var(--pickled-bluewood)]">
                          {v == null ? (
                            <span className="text-[var(--heather)]">—</span>
                          ) : (
                            String(v)
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </details>

              {/* Mappings */}
              <div>
                <div className="mb-2 flex items-center justify-between">
                  <h4 className="m-0 text-xs font-semibold uppercase tracking-wide text-[var(--slate)]">
                    Mappings
                  </h4>
                  <button
                    type="button"
                    onClick={() => setPickerOpen((v) => !v)}
                    disabled={availableCaps.length === 0}
                    className="inline-flex items-center gap-1 rounded border border-[var(--coral)] bg-white px-2 py-0.5 text-[10px] text-[var(--coral)] hover:bg-[var(--forget-me-not)] disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <Plus className="h-2.5 w-2.5" /> Add mapping
                  </button>
                </div>

                {pickerOpen && (
                  <div className="mb-2 rounded border border-[var(--geyser)] bg-white p-2">
                    <p className="m-0 mb-1 text-[10px] text-[var(--slate)]">
                      Pick an L2 capability:
                    </p>
                    <ul className="flex flex-wrap gap-1">
                      {availableCaps.map((cap) => (
                        <li key={cap.id}>
                          <button
                            type="button"
                            onClick={() => void addMapping(cap.id)}
                            disabled={adding}
                            className="rounded-full border border-[var(--geyser)] bg-white px-2 py-0.5 text-[10px] text-[var(--pickled-bluewood)] hover:border-[var(--cerulean)] disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            {cap.name}
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {app.mappings.length === 0 ? (
                  <p className="text-xs italic text-[var(--heather)]">
                    No mappings yet.
                  </p>
                ) : (
                  <ul className="flex flex-col gap-1.5">
                    {app.mappings.map((m) => (
                      <li
                        key={m.id}
                        className={cn(
                          "rounded border bg-white p-2 text-xs",
                          m.status === "confirmed" &&
                            "border-[var(--jade)]/40",
                          m.status === "dismissed" &&
                            "border-[var(--watermelon)]/40 opacity-60",
                          m.status === "suggested" &&
                            "border-[var(--geyser)]",
                        )}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-medium text-[var(--pickled-bluewood)]">
                            {capName(m.capability_id)}
                          </span>
                          <span className="flex items-center gap-1">
                            <span className="font-mono text-[10px] text-[var(--slate)]">
                              {m.confidence.toFixed(2)}
                            </span>
                            <span className="text-[10px] uppercase tracking-wide text-[var(--slate)]">
                              {m.status}
                            </span>
                          </span>
                        </div>
                        <p className="m-0 mt-1 text-[10px] text-[var(--slate)]">
                          {m.rationale}
                        </p>
                        <div className="mt-1 flex items-center gap-1">
                          {m.status !== "confirmed" && (
                            <button
                              type="button"
                              onClick={() => void flip(m.id, "confirmed")}
                              disabled={busyMappingId === m.id}
                              className="inline-flex items-center gap-1 rounded border border-[var(--jade)] bg-white px-1.5 py-0.5 text-[10px] text-[var(--jade)] hover:bg-[var(--jade)]/10 disabled:opacity-50"
                            >
                              <CheckCircle2 className="h-2.5 w-2.5" /> Confirm
                            </button>
                          )}
                          {m.status !== "dismissed" && (
                            <button
                              type="button"
                              onClick={() => void flip(m.id, "dismissed")}
                              disabled={busyMappingId === m.id}
                              className="inline-flex items-center gap-1 rounded border border-[var(--watermelon)] bg-white px-1.5 py-0.5 text-[10px] text-[var(--watermelon)] hover:bg-[var(--watermelon)]/10 disabled:opacity-50"
                            >
                              <XCircle className="h-2.5 w-2.5" /> Dismiss
                            </button>
                          )}
                          <span className="ml-auto text-[10px] text-[var(--heather)]">
                            {m.engine_version}
                          </span>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function InferredField({
  label,
  value,
}: {
  label: string;
  value: string | null;
}) {
  return (
    <>
      <dt className="text-[var(--slate)]">{label}</dt>
      <dd className="m-0 text-[var(--pickled-bluewood)]">
        {value ?? <span className="text-[var(--heather)]">—</span>}
      </dd>
    </>
  );
}
