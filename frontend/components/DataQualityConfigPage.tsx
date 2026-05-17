"use client";

import {
  Loader2,
  Plus,
  Settings2,
  Sparkles,
  Trash2,
  Wand2,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import {
  api,
  ApiError,
  isDqConfigSaved,
  type DqAlgorithm,
  type DqColumnMapping,
  type DqConfigOrDraft,
  type DqParser,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const NORMALIZATION_RULES: ReadonlyArray<{
  key: string;
  label: string;
  example: string;
}> = [
  {
    key: "case_fold",
    label: "Case normalization",
    example: "ACME ROBOTICS INC → acme robotics inc",
  },
  {
    key: "collapse_whitespace",
    label: "Whitespace handling",
    example: '"  Helix  Pharmaceuticals  " → "Helix Pharmaceuticals"',
  },
  {
    key: "strip_punctuation",
    label: "Punctuation stripping",
    example: "Acme Robotics, Inc → Acme Robotics Inc",
  },
  {
    key: "nfkd_fold",
    label: "Unicode normalization (NFKD + accent fold)",
    example: "Café Lumière → Cafe Lumiere",
  },
  {
    key: "strip_special_chars",
    label: "Special character handling",
    example: "Café Lumière ☕ → Café Lumière",
  },
  {
    key: "strip_corporate_suffix",
    label: "Corporate suffix removal",
    example: "Acme Robotics Inc / Acme Robotics LLC → Acme Robotics",
  },
  {
    key: "expand_address_abbrev",
    label: "Address abbreviation expansion",
    example: "120 Market St. → 120 Market Street",
  },
];

const ALGORITHM_LABELS: Record<DqAlgorithm, string> = {
  exact: "Exact match",
  levenshtein: "Edit distance (Levenshtein)",
  jaro_winkler: "Jaro-Winkler",
  jaccard_tokens: "Token Jaccard",
  cosine_tokens: "Token cosine",
  soundex: "Soundex (phonetic)",
  metaphone: "Metaphone (phonetic)",
  ngram: "Character n-gram",
  numeric_tolerance: "Numeric tolerance",
  date_proximity: "Date proximity",
};

const ALGORITHM_OPTIONS: DqAlgorithm[] = Object.keys(
  ALGORITHM_LABELS,
) as DqAlgorithm[];

const PARSER_LABELS: Record<DqParser | "none", string> = {
  none: "— none —",
  email: "Email (lowercase)",
  phone: "Phone (E.164)",
  date: "Date (ISO 8601)",
};

type DraftForm = {
  sheetA: string;
  sheetB: string;
  normalization: Record<string, boolean>;
  threshold: number;
  mappings: DqColumnMapping[];
};

function emptyMapping(): DqColumnMapping {
  return {
    column_a: "",
    column_b: "",
    algorithm: "exact",
    weight: 1.0,
    is_important: false,
    parser: null,
    recommended_by: "user",
  };
}

function clamp01(n: number): number {
  if (Number.isNaN(n)) return 0;
  if (n < 0) return 0;
  if (n > 1) return 1;
  return n;
}

export default function DataQualityConfigPage({
  projectId,
  datasetId,
  availableSheets,
  onComplete,
}: {
  projectId: number;
  datasetId: number;
  availableSheets: string[];
  onComplete: () => void;
}) {
  const [draft, setDraft] = useState<DraftForm | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [llmBusy, setLlmBusy] = useState(false);
  const [llmNote, setLlmNote] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const cfg: DqConfigOrDraft = await api.getSimilarityConfig(
        projectId,
        datasetId,
      );
      if (isDqConfigSaved(cfg)) {
        setDraft({
          sheetA: cfg.sheet_a ?? availableSheets[0] ?? "",
          sheetB: cfg.sheet_b ?? availableSheets[1] ?? "",
          normalization: cfg.normalization,
          threshold: cfg.threshold,
          mappings: cfg.mappings,
        });
      } else {
        setDraft({
          sheetA: cfg.suggested_sheet_a ?? availableSheets[0] ?? "",
          sheetB: cfg.suggested_sheet_b ?? availableSheets[1] ?? "",
          normalization: cfg.normalization,
          threshold: cfg.threshold,
          mappings: cfg.mappings,
        });
      }
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : "Failed to load config");
    } finally {
      setLoading(false);
    }
  }, [projectId, datasetId, availableSheets]);

  useEffect(() => {
    void load();
  }, [load]);

  async function refetchHeuristic(sheetA: string, sheetB: string) {
    // sheetA == sheetB is allowed and means within-sheet dedup (the
    // recommender returns self-mappings in that case).
    if (!sheetA || !sheetB) return;
    try {
      const rec = await api.recommendSimilarityConfig(projectId, datasetId, {
        sheet_a: sheetA,
        sheet_b: sheetB,
      });
      setDraft((prev) =>
        prev
          ? {
              ...prev,
              normalization: rec.normalization,
              threshold: rec.threshold,
              mappings: rec.mappings,
            }
          : prev,
      );
    } catch (e: unknown) {
      setError(
        e instanceof ApiError ? e.message : "Failed to refresh recommendation",
      );
    }
  }

  async function handleImproveWithLlm() {
    if (!draft) return;
    setLlmBusy(true);
    setLlmNote(null);
    setError(null);
    try {
      const rec = await api.recommendSimilarityConfigWithLlm(
        projectId,
        datasetId,
        {
          sheet_a: draft.sheetA,
          sheet_b: draft.sheetB,
          existing_mappings: draft.mappings,
        },
      );
      setDraft({ ...draft, mappings: rec.mappings });
      if (rec.llm_error) setLlmNote(rec.llm_error);
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : "LLM refinement failed");
    } finally {
      setLlmBusy(false);
    }
  }

  function validate(d: DraftForm): string | null {
    if (!d.sheetA || !d.sheetB) return "Pick a sheet to analyze.";
    // sheet_a == sheet_b is supported (within-sheet dedup).
    if (d.mappings.length === 0) return "Add at least one column mapping.";
    for (const m of d.mappings) {
      if (!m.column_a || !m.column_b)
        return "Every mapping needs both a Sheet A and a Sheet B column.";
    }
    if (!d.mappings.some((m) => m.is_important))
      return "Mark at least one mapping as Important. Important columns drive cluster formation.";
    return null;
  }

  async function saveOnly() {
    if (!draft) return;
    const v = validate(draft);
    if (v) {
      setError(v);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await api.saveSimilarityConfig(projectId, datasetId, {
        sheet_a: draft.sheetA,
        sheet_b: draft.sheetB,
        normalization: draft.normalization,
        threshold: draft.threshold,
        mappings: draft.mappings,
      });
      onComplete();
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  async function saveAndRun() {
    if (!draft) return;
    const v = validate(draft);
    if (v) {
      setError(v);
      return;
    }
    setRunning(true);
    setError(null);
    try {
      await api.saveSimilarityConfig(projectId, datasetId, {
        sheet_a: draft.sheetA,
        sheet_b: draft.sheetB,
        normalization: draft.normalization,
        threshold: draft.threshold,
        mappings: draft.mappings,
      });
      await api.runSimilarity(projectId, datasetId);
      onComplete();
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : "Run failed");
    } finally {
      setRunning(false);
    }
  }

  async function skip() {
    setError(null);
    try {
      await api.skipSimilarityConfig(projectId, datasetId);
      onComplete();
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : "Skip failed");
    }
  }

  if (loading) {
    return (
      <section className="card flex items-center gap-2 !p-4">
        <Loader2 className="h-4 w-4 animate-spin text-[var(--slate)]" />
        <span className="text-sm text-[var(--slate)]">
          Loading similarity configuration...
        </span>
      </section>
    );
  }
  if (!draft) {
    return (
      <section className="card !p-4 text-sm text-[var(--watermelon)]">
        {error ?? "Could not load configuration."}
      </section>
    );
  }

  const validationMsg = validate(draft);

  return (
    <section
      className="card flex flex-col gap-4 !p-0"
      aria-label="Profiling setup and configuration"
    >
      <header className="flex items-center justify-between gap-2 border-b border-[var(--geyser)] px-4 py-3">
        <div className="flex items-center gap-2">
          <Settings2 className="h-4 w-4 text-[var(--cerulean)]" />
          <h2 className="m-0 text-base font-semibold text-[var(--pickled-bluewood)]">
            Profiling Setup &amp; Configuration
          </h2>
        </div>
        <button
          type="button"
          onClick={() => void skip()}
          className="text-xs text-[var(--slate)] underline hover:text-[var(--coral)]"
        >
          Skip similarity scoring
        </button>
      </header>

      {/* Step 1 — sheet picker. Single-sheet workbooks render one picker;
          multi-sheet workbooks render two with a hint that picking the
          same sheet for both means within-sheet dedup. */}
      <div className="px-4">
        {availableSheets.length <= 1 ? (
          <>
            <h3 className="m-0 mb-2 text-sm font-semibold text-[var(--pickled-bluewood)]">
              1. Sheet to analyze
            </h3>
            <div className="flex flex-wrap items-center gap-3">
              <label className="flex items-center gap-2 text-xs text-[var(--slate)]">
                Sheet
                <select
                  value={draft.sheetA}
                  onChange={(e) => {
                    const sheet = e.target.value;
                    setDraft({ ...draft, sheetA: sheet, sheetB: sheet });
                    void refetchHeuristic(sheet, sheet);
                  }}
                  aria-label="Sheet"
                  className="rounded border border-[var(--geyser)] bg-white px-2 py-1 text-sm text-[var(--pickled-bluewood)]"
                >
                  <option value="">— pick —</option>
                  {availableSheets.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              </label>
              <span className="text-xs text-[var(--heather)]">
                Single sheet → within-sheet dedup (find duplicate rows).
              </span>
            </div>
          </>
        ) : (
          <>
            <h3 className="m-0 mb-2 text-sm font-semibold text-[var(--pickled-bluewood)]">
              1. Sheets to compare
            </h3>
            <div className="flex flex-wrap items-center gap-3">
              <label className="flex items-center gap-2 text-xs text-[var(--slate)]">
                Sheet A
                <select
                  value={draft.sheetA}
                  onChange={(e) => {
                    const sheetA = e.target.value;
                    setDraft({ ...draft, sheetA });
                    void refetchHeuristic(sheetA, draft.sheetB);
                  }}
                  aria-label="Sheet A"
                  className="rounded border border-[var(--geyser)] bg-white px-2 py-1 text-sm text-[var(--pickled-bluewood)]"
                >
                  <option value="">— pick —</option>
                  {availableSheets.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex items-center gap-2 text-xs text-[var(--slate)]">
                Sheet B
                <select
                  value={draft.sheetB}
                  onChange={(e) => {
                    const sheetB = e.target.value;
                    setDraft({ ...draft, sheetB });
                    void refetchHeuristic(draft.sheetA, sheetB);
                  }}
                  aria-label="Sheet B"
                  className="rounded border border-[var(--geyser)] bg-white px-2 py-1 text-sm text-[var(--pickled-bluewood)]"
                >
                  <option value="">— pick —</option>
                  {availableSheets.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <p className="m-0 mt-1 text-xs text-[var(--heather)]">
              Pick the same sheet for both to find duplicate rows within
              one sheet; pick two different sheets to link records across
              them.
            </p>
          </>
        )}
      </div>

      {/* Step 2 — normalization */}
      <div className="px-4">
        <h3 className="m-0 mb-2 text-sm font-semibold text-[var(--pickled-bluewood)]">
          2. Normalization rules
        </h3>
        <ul className="grid gap-1 sm:grid-cols-2">
          {NORMALIZATION_RULES.map((rule) => (
            <li key={rule.key} className="flex items-start gap-2">
              <input
                type="checkbox"
                id={`norm-${rule.key}`}
                checked={!!draft.normalization[rule.key]}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    normalization: {
                      ...draft.normalization,
                      [rule.key]: e.target.checked,
                    },
                  })
                }
                className="mt-1 h-3.5 w-3.5"
              />
              <label
                htmlFor={`norm-${rule.key}`}
                className="text-xs leading-tight text-[var(--pickled-bluewood)]"
              >
                <span className="font-medium">{rule.label}</span>
                <span className="ml-1 block font-mono text-[10px] text-[var(--heather)]">
                  {rule.example}
                </span>
              </label>
            </li>
          ))}
        </ul>
      </div>

      {/* Step 3 — column mappings */}
      <div className="px-4">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <h3 className="m-0 text-sm font-semibold text-[var(--pickled-bluewood)]">
            3. Column mappings &amp; algorithms
          </h3>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() =>
                void refetchHeuristic(draft.sheetA, draft.sheetB)
              }
              className="inline-flex items-center gap-1 rounded border border-[var(--geyser)] bg-white px-2 py-1 text-xs text-[var(--pickled-bluewood)] hover:border-[var(--cerulean)] hover:text-[var(--cerulean)]"
            >
              <Wand2 className="h-3 w-3" /> Auto-map
            </button>
            <button
              type="button"
              onClick={() => void handleImproveWithLlm()}
              disabled={llmBusy || draft.mappings.length === 0}
              className="inline-flex items-center gap-1 rounded border border-[var(--coral)] bg-white px-2 py-1 text-xs text-[var(--coral)] hover:bg-[var(--forget-me-not)] disabled:cursor-not-allowed disabled:opacity-50"
            >
              {llmBusy ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Sparkles className="h-3 w-3" />
              )}
              Improve with AI
            </button>
          </div>
        </div>
        {llmNote && (
          <p className="mb-2 text-xs text-[var(--watermelon)]">{llmNote}</p>
        )}

        <table
          className="w-full border-collapse text-xs"
          aria-label="Column mappings"
        >
          <thead>
            <tr className="border-b border-[var(--geyser)] text-left text-[var(--slate)]">
              <th className="px-1 py-1 font-medium">{draft.sheetA || "Sheet A"}</th>
              <th className="px-1 py-1 font-medium">{draft.sheetB || "Sheet B"}</th>
              <th className="px-1 py-1 font-medium">Algorithm</th>
              <th className="px-1 py-1 font-medium">Parser</th>
              <th className="px-1 py-1 font-medium">Weight</th>
              <th className="px-1 py-1 font-medium" title="Important columns drive cluster formation">
                Important
              </th>
              <th className="px-1 py-1 font-medium">Src</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {draft.mappings.map((m, idx) => (
              <tr
                key={idx}
                className={cn(
                  "border-b border-[var(--geyser)]",
                  m.is_important && "bg-[var(--forget-me-not)]/30",
                )}
              >
                <td className="px-1 py-1">
                  <input
                    type="text"
                    value={m.column_a}
                    onChange={(e) =>
                      setDraft({
                        ...draft,
                        mappings: draft.mappings.map((x, i) =>
                          i === idx ? { ...x, column_a: e.target.value } : x,
                        ),
                      })
                    }
                    aria-label={`Mapping ${idx} column A`}
                    className="w-full rounded border border-[var(--geyser)] bg-white px-1 py-0.5 text-xs"
                  />
                </td>
                <td className="px-1 py-1">
                  <input
                    type="text"
                    value={m.column_b}
                    onChange={(e) =>
                      setDraft({
                        ...draft,
                        mappings: draft.mappings.map((x, i) =>
                          i === idx ? { ...x, column_b: e.target.value } : x,
                        ),
                      })
                    }
                    aria-label={`Mapping ${idx} column B`}
                    className="w-full rounded border border-[var(--geyser)] bg-white px-1 py-0.5 text-xs"
                  />
                </td>
                <td className="px-1 py-1">
                  <select
                    value={m.algorithm}
                    onChange={(e) =>
                      setDraft({
                        ...draft,
                        mappings: draft.mappings.map((x, i) =>
                          i === idx
                            ? { ...x, algorithm: e.target.value as DqAlgorithm }
                            : x,
                        ),
                      })
                    }
                    aria-label={`Mapping ${idx} algorithm`}
                    className="w-full rounded border border-[var(--geyser)] bg-white px-1 py-0.5 text-xs"
                  >
                    {ALGORITHM_OPTIONS.map((a) => (
                      <option key={a} value={a}>
                        {ALGORITHM_LABELS[a]}
                      </option>
                    ))}
                  </select>
                </td>
                <td className="px-1 py-1">
                  <select
                    value={m.parser ?? "none"}
                    onChange={(e) => {
                      const v = e.target.value;
                      setDraft({
                        ...draft,
                        mappings: draft.mappings.map((x, i) =>
                          i === idx
                            ? {
                                ...x,
                                parser:
                                  v === "none" ? null : (v as DqParser),
                              }
                            : x,
                        ),
                      });
                    }}
                    aria-label={`Mapping ${idx} parser`}
                    className="w-full rounded border border-[var(--geyser)] bg-white px-1 py-0.5 text-xs"
                  >
                    {(Object.keys(PARSER_LABELS) as Array<keyof typeof PARSER_LABELS>).map(
                      (k) => (
                        <option key={k} value={k}>
                          {PARSER_LABELS[k]}
                        </option>
                      ),
                    )}
                  </select>
                </td>
                <td className="px-1 py-1">
                  <input
                    type="number"
                    min={0}
                    max={1}
                    step={0.05}
                    value={m.weight}
                    onChange={(e) =>
                      setDraft({
                        ...draft,
                        mappings: draft.mappings.map((x, i) =>
                          i === idx
                            ? { ...x, weight: clamp01(Number(e.target.value)) }
                            : x,
                        ),
                      })
                    }
                    aria-label={`Mapping ${idx} weight`}
                    className="w-16 rounded border border-[var(--geyser)] bg-white px-1 py-0.5 text-right text-xs"
                  />
                </td>
                <td className="px-1 py-1 text-center">
                  <input
                    type="checkbox"
                    checked={m.is_important}
                    onChange={(e) =>
                      setDraft({
                        ...draft,
                        mappings: draft.mappings.map((x, i) =>
                          i === idx
                            ? { ...x, is_important: e.target.checked }
                            : x,
                        ),
                      })
                    }
                    aria-label={`Mapping ${idx} important`}
                    className="h-3.5 w-3.5"
                  />
                </td>
                <td className="px-1 py-1 text-[10px] uppercase tracking-wide text-[var(--heather)]">
                  {m.recommended_by}
                </td>
                <td className="px-1 py-1">
                  <button
                    type="button"
                    onClick={() =>
                      setDraft({
                        ...draft,
                        mappings: draft.mappings.filter((_, i) => i !== idx),
                      })
                    }
                    aria-label={`Remove mapping ${idx}`}
                    className="grid h-6 w-6 place-items-center rounded text-[var(--slate)] hover:bg-[var(--fog)] hover:text-[var(--watermelon)]"
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </td>
              </tr>
            ))}
            {draft.mappings.length === 0 && (
              <tr>
                <td colSpan={8} className="px-2 py-3 text-center text-[var(--heather)]">
                  No mappings yet. Click Auto-map to populate, or Add row.
                </td>
              </tr>
            )}
          </tbody>
        </table>
        <button
          type="button"
          onClick={() =>
            setDraft({ ...draft, mappings: [...draft.mappings, emptyMapping()] })
          }
          className="mt-2 inline-flex items-center gap-1 rounded border border-[var(--geyser)] bg-white px-2 py-1 text-xs text-[var(--pickled-bluewood)] hover:border-[var(--cerulean)] hover:text-[var(--cerulean)]"
        >
          <Plus className="h-3 w-3" /> Add row
        </button>
      </div>

      {/* Step 4 — threshold + actions */}
      <div className="border-t border-[var(--geyser)] px-4 py-3">
        <h3 className="m-0 mb-2 text-sm font-semibold text-[var(--pickled-bluewood)]">
          4. Threshold &amp; run
        </h3>
        <div className="mb-3 flex items-center gap-3">
          <label className="text-xs text-[var(--slate)]" htmlFor="dq-threshold">
            Cluster threshold ({draft.threshold.toFixed(2)})
          </label>
          <input
            id="dq-threshold"
            type="range"
            min={0}
            max={1}
            step={0.01}
            value={draft.threshold}
            onChange={(e) =>
              setDraft({ ...draft, threshold: clamp01(Number(e.target.value)) })
            }
            aria-label="Cluster threshold"
            className="flex-1"
          />
        </div>
        {validationMsg && (
          <p className="mb-2 text-xs text-[var(--watermelon)]">{validationMsg}</p>
        )}
        {error && (
          <p role="alert" className="mb-2 text-xs text-[var(--watermelon)]">
            {error}
          </p>
        )}
        <div className="flex flex-wrap items-center justify-end gap-2">
          <button
            type="button"
            onClick={() => void saveOnly()}
            disabled={!!validationMsg || saving || running}
            className="inline-flex items-center gap-1 rounded border border-[var(--geyser)] bg-white px-3 py-1 text-xs text-[var(--pickled-bluewood)] hover:border-[var(--cerulean)] hover:text-[var(--cerulean)] disabled:cursor-not-allowed disabled:opacity-50"
          >
            {saving && <Loader2 className="h-3 w-3 animate-spin" />}
            Save only
          </button>
          <button
            type="button"
            onClick={() => void saveAndRun()}
            disabled={!!validationMsg || saving || running}
            className="inline-flex items-center gap-1 rounded bg-[var(--coral)] px-3 py-1 text-xs font-medium text-white hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {running && <Loader2 className="h-3 w-3 animate-spin" />}
            Save &amp; Run
          </button>
        </div>
      </div>
    </section>
  );
}
