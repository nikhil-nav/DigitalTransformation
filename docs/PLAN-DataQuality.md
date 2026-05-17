# Data Quality Assessment - Implementation Plan

A 6-part plan. The user must explicitly approve each completed part before
the next begins.

## Cross-cutting commitments (precision before speed)

- **Full dataset, no sampling.** Every check runs on every row in every sheet
  of the uploaded workbook. Stats are deterministic.
- **Conservative type inference.** Semantic types (date, numeric, email,
  phone, etc.) are only assigned when ≥99% of non-null values conform under
  explicit parsers. Below that threshold the column is `mixed` and the
  non-conforming values are surfaced as issues, never silently coerced.
- **Pattern detection is a curated catalogue,** not a guess. Email (RFC 5322
  simplified), E.164 phones, ISO 8601 dates, UUID, URL, IPv4/v6, US/CA postal
  codes, currency. Each candidate must match ≥95% of non-null values; non-
  conforming values are reported as counter-examples.
- **Outliers reported through two methods.** Tukey IQR fence (1.5× standard,
  3× extreme) and modified z-score on MAD for skewed data. Both numbers are
  visible in the dashboard; no single threshold hides disagreement.
- **Cross-sheet relationships are suggestions only.** Every candidate is
  `status="suggested"` until the user explicitly confirms. Confidence score
  is multi-signal: exact type match, % of child values present in parent
  (subset coverage), cardinality plausibility, name similarity. All four
  exposed.
- **AI annotation never overrides stats.** RAG ratings, counts, and
  percentages all come from the deterministic engine. The AI agent only
  contributes narrative and suggested fix; if its JSON output fails schema
  validation after one retry, the issue is marked `ai_annotation_failed`
  with the raw response retained.
- **No issue cap on AI annotation.** Every detected issue is annotated.
  Batched LLM calls (≤20 issues per call) manage cost without dropping data.
- **Reproducibility.** Every `ColumnProfile` and `Issue` row records the
  stats-engine version, the timestamp, and the input file SHA-256. Re-running
  with the same workbook and engine version produces identical rows.
- **Chat agent answers from pandas/SQL only.** Tool calls return actual rows
  from the dataset or persisted profile rows. Answers without specific
  sheet/column/value citations are treated as a tool-call failure.

## Test stack

Same as the BCM build: pytest backend (with `hypothesis` for stats
invariants), Vitest + RTL frontend, Playwright if/when end-to-end is
needed.

---

## Part 1 - Plan & migration

Goal: Get this plan approved. Activate the `data_quality_assessment`
project type. Generalise the chat tables so both BCM and Data Quality share
them.

Checklist:
- [ ] `docs/PLAN-DataQuality.md` committed (this file)
- [ ] `data_quality_assessment` flipped to `is_active: True` in
  `backend/app/db.py:72`
- [ ] Rename `BcmChatThread` → `ChatThread` (table `chat_threads`) and
  `BcmChatMessage` → `ChatMessage` (table `chat_messages`)
- [ ] Add `scope: str` column on both tables, NOT NULL, default `"bcm"`,
  with a check constraint `scope IN ('bcm','data_quality')`
- [ ] One-shot SQLite migration in `init_db`: detect old tables, rename
  to new names, add `scope` column populated to `"bcm"`. Idempotent and
  safe to re-run.
- [ ] Update `app/bcm.py`, `app/threads.py`, `app/llm/agent.py`,
  `app/db.py` (the orphan-thread migration) to use the new model names and
  filter/insert with `scope="bcm"`.
- [ ] Update `tests/test_bcm.py`, `tests/test_threads.py`,
  `tests/test_llm.py` imports
- [ ] User approves Part 1

Tests / success criteria:
- All existing pytest tests pass unchanged (BCM behaviour is preserved).
- Backend boots clean against a pre-existing SQLite database that has
  `bcm_chat_threads` and `bcm_chat_messages` populated; rows are migrated
  with `scope="bcm"` and no FK breakage.
- Backend also boots clean against an empty SQLite database.
- New project flow (frontend) shows "Data Quality Assessment" as a
  selectable type.

Notes / risk:
- SQLite supports `ALTER TABLE ... RENAME TO` and `ALTER TABLE ... ADD
  COLUMN`. FK references update transparently. We will verify with a
  fresh DB and with the existing dev DB before claiming success.

---

## Part 2 - Excel ingestion + sheet detection

Goal: User can create a Data Quality project, upload an `.xlsx`, and see the
list of sheets the workbook contains.

Checklist:
- [ ] Add `pandas` and `openpyxl` to `backend/pyproject.toml`
- [ ] New model `DataQualityDataset`: `id`, `project_id` (FK → projects,
  cascade), `original_filename`, `local_path` (str), `file_sha256` (str,
  64 chars), `sheet_names_json` (text, list of sheet names), `row_count_json`
  (text, map of sheet → row count), `column_count_json` (text, map of sheet
  → column count), `engine_version` (str), `uploaded_at`, `profiled_at`
  (nullable, set when profile completes)
- [ ] Endpoints (new module `app/data_quality/router.py`):
  - `POST /api/projects/{id}/dq/datasets` (multipart, single .xlsx upload)
  - `GET /api/projects/{id}/dq/datasets`
  - `GET /api/projects/{id}/dq/datasets/{ds_id}`
  - `DELETE /api/projects/{id}/dq/datasets/{ds_id}` (deletes file from disk
    too)
- [ ] Project type gate: `project.project_type.code ==
  "data_quality_assessment"`, otherwise 400
- [ ] Storage path: `{DT_DATA_DIR}/data_quality/{project_id}/{file_sha256}.xlsx`
- [ ] Reject: non-xlsx mime, size > 25MB, password-protected workbooks
- [ ] Frontend: gate-conditional `DataQualitySection.tsx` in
  `ProjectDetail.tsx`. Upload card (drag/drop). Datasets list with sheet
  names + row counts.

Tests / success criteria:
- Pytest covers: happy-path upload + retrieval; oversize rejection; non-xlsx
  rejection; project-type gate; delete removes both DB row and file from
  disk; sheet detection on a multi-sheet workbook.
- Vitest covers `DataQualitySection` empty state, post-upload state.
- Manual: upload a real workbook, see sheets listed.

Risk: openpyxl's `read_only=True` mode is required for memory safety on
large workbooks. Sheet metadata is cheap; full row counts may stream-iterate
in worst case.

---

## Part 3 - Statistical engine (single-sheet)

Goal: Compute and persist the full per-sheet profile, covering US 1.1–1.7,
2.0, 2.1. No AI in this part - pure pandas.

Checklist:
- [ ] New module `app/data_quality/stats.py` with pure functions:
  - `profile_sheet(df: DataFrame) -> SheetProfile`
  - `infer_semantic_type(series) -> SemanticType`
  - `detect_patterns(series) -> list[PatternMatch]`
  - `detect_outliers(series) -> OutlierReport` (Tukey IQR + modified
    z-score on MAD)
  - `detect_duplicate_columns(df) -> list[tuple]`
  - `detect_duplicate_rows(df) -> int`
- [ ] Models:
  - `DataQualitySheetProfile(id, dataset_id, sheet_name, row_count,
    column_count, exact_duplicate_row_count, completeness_pct, rag,
    engine_version, computed_at)`
  - `DataQualityColumnProfile(id, sheet_profile_id, name, ordinal,
    inferred_dtype, semantic_type, null_count, null_pct, distinct_count,
    distinct_pct, top_values_json, numeric_min, numeric_max, numeric_mean,
    numeric_median, numeric_std, numeric_p25, numeric_p75, date_min,
    date_max, pattern_label, pattern_conformance_pct, outlier_iqr_count,
    outlier_mad_count, type_mismatch_count, range_min, range_max,
    range_violation_count, rag, computed_at)`
  - `DataQualityIssue(id, dataset_id, sheet_name, column_name, dimension,
    severity, description, sample_value_count, sample_values_json,
    engine_version, ai_narrative, ai_fix, ai_status, created_at)`
- [ ] Profiling runs synchronously inside the upload endpoint from Part 2.
  Optional re-profile endpoint: `POST /api/projects/{id}/dq/datasets/{ds_id}/profile`
- [ ] Endpoints to fetch profile: `GET .../datasets/{ds_id}/profile`,
  `GET .../datasets/{ds_id}/issues`
- [ ] Bounds editor: `PATCH .../datasets/{ds_id}/sheets/{sheet}/columns/{col}/bounds`
  with `{min, max}` triggers re-profile for that column only

Tests / success criteria:
- Pytest fixtures with deterministic xlsx files asserting every metric
  exactly.
- Hypothesis tests for invariants: `null_count + non_null_count == row_count`;
  `completeness_pct in [0, 100]`; `distinct_count <= row_count`;
  `len(outliers_iqr) >= 0`; pattern conformance % is in [0, 100].
- Profile of a 10k-row sheet completes in <3s on a dev laptop.

Notes: `engine_version` is a constant string in `stats.py` (e.g. `"1.0.0"`).
Bump it for any change that alters output.

---

## Part 4 - Cross-column + cross-sheet (US 1.8, 1.9)

Goal: Detect intra-sheet dependencies and inter-sheet referential
candidates.

Checklist:
- [ ] Cross-column (US 1.8):
  - Functional dependency: for each candidate (A → B), verify that
    grouping by A yields a single B value per group; emit
    `DataQualityFunctionalDependency` with confidence (% of groups
    consistent) and counter-examples
  - Numeric Pearson correlation; flag pairs with |r| > 0.95 as
    `redundancy_candidate` issues
- [ ] Cross-sheet (US 1.9):
  - For each (sheet_a.col_x, sheet_b.col_y) pair where types match,
    compute: name_similarity (Jaccard on tokens), subset_coverage (%
    of child distinct values present in parent), cardinality (child→parent
    must be M:1 or 1:1 for FK), null tolerance
  - Persist `DataQualityRelationship(id, dataset_id, parent_sheet,
    parent_column, child_sheet, child_column, type_match, name_similarity,
    subset_coverage, cardinality, confidence, status, suggested_at,
    confirmed_at, dismissed_at, confirmed_by)`
  - `status` starts `suggested`; user actions update to `confirmed` or
    `dismissed`. Confirmation status drives downstream FK violation checks.
- [ ] Endpoints:
  - `GET .../datasets/{id}/relationships`
  - `PATCH .../datasets/{id}/relationships/{rel_id}` (`{status:
    confirmed | dismissed}`)
- [ ] When a relationship is `confirmed`, emit
  `DataQualityIssue(dimension="fk_violation")` for every child value not
  present in parent.

Tests / success criteria:
- Synthetic 2-sheet workbook (customers + orders) correctly proposes
  `orders.customer_id → customers.id` with subset_coverage 100% and
  confidence high. Cardinality detected as M:1.
- Mismatched values raise issue rows once relationship is confirmed.
- Pytest covers FD detection (positive + negative case), correlation
  redundancy flag, FK suggestion ranking.

---

## Part 5 - AI agent + model picker

Goal: After stats finish, the AI agent annotates every detected issue with
a narrative and a suggested fix. User can pick the model variant per
provider.

Checklist:
- [ ] Extend `LlmKeysRequest` and `LlmKeysStatus` to include `model: str`.
  Frontend `LlmSettings.tsx` gains a model dropdown:
  - Anthropic: `claude-opus-4-7`, `claude-sonnet-4-6`, `claude-haiku-4-5-20251001`
  - OpenAI: `gpt-5`, `o4-mini` (subject to availability)
- [ ] Persist the chosen model on the session keys row; default if unset
  is each provider's default in `app/llm/provider.py`.
- [ ] New module `app/data_quality/annotator.py`:
  - `annotate_issues(db, dataset_id, keys, max_batch=20) -> AnnotationReport`
  - Builds a structured prompt per batch with the dataset summary + N issue
    rows; expects JSON `{annotations: [{issue_id, narrative, suggested_fix}]}`
  - Schema-validates the response. One retry on parse failure. If still
    failing, mark each affected issue `ai_status="failed"` with the raw
    response stored in a debug column.
- [ ] Annotator runs as the final step of the upload pipeline. Status
  surfaced via the dataset row: `profile_status` (`pending|running|done`),
  `annotation_status` (`pending|running|done|failed`).
- [ ] Endpoint: `POST .../datasets/{id}/annotate` (re-annotate on demand).

Tests / success criteria:
- Pytest mocks the provider; verifies schema validation, retry, and
  failed-but-preserved path.
- Real upload with a real Anthropic key annotates every issue end-to-end.
- Stats dashboard still works if AI annotation fails (graceful
  degradation).

---

## Part 6 - Dashboard + chat panel

Goal: The full Data Quality dashboard with a chat side-panel for ad-hoc
questions on the loaded dataset.

Checklist:
- [ ] Add `plotly.js-dist-min` + `react-plotly.js` to frontend deps.
  Dynamic-import the Plotly bundle (cytoscape pattern).
- [ ] `DataQualityDashboard.tsx`:
  - KPI strip: total rows, total columns, completeness %, RAG indicator
  - Sheet tabs (one per sheet)
  - Per sheet: completeness donut, issue-severity bar chart, sortable
    columns table (name, type, null%, distinct, RAG, issue count)
  - Click a column → drawer with histogram/bar distribution, pattern-
    frequency pie, sample values, full issue list with AI narrative
  - Bounds editor inside the column drawer
  - Cross-table tab: FK relationship graph (reuse cytoscape) +
    relationship list with confirm/dismiss action, violations table
- [ ] Chat side-panel: reuse `ChatPanel` with `scope="data_quality"`.
  Starter prompts: "Which columns have the worst data quality?",
  "Suggest fixes for the email column", "Are there orphan rows in
  orders?"
- [ ] New agent system prompt + tools in `app/data_quality/agent.py`:
  - `describe_dataset(dataset_id)` - sheet list + summary
  - `describe_column(sheet, column)` - returns persisted profile row
  - `list_issues(severity?, sheet?)` - filterable issue list
  - `query_dataset(sheet, filter_expr, limit)` - safe pandas query
    (whitelisted expressions only), returns actual rows
  - `flag_issue(sheet, column, severity, description)` - lets the agent
    record a new issue
- [ ] System prompt requires the agent to cite specific sheet/column/value
  in every answer; the tool layer rejects answers that don't.

Tests / success criteria:
- E2E demo: upload xlsx → see dashboard with charts and RAG → click
  column → see distribution + AI narrative → ask chat "which columns
  should I clean first" → coherent answer citing specific profile rows.
- Vitest covers `DataQualityDashboard` rendering with fixture data,
  cross-table tab confirm/dismiss flow.
- Pytest covers `query_dataset` whitelist (rejects arbitrary pandas eval).

---

## Out of scope (deferred)

- Multi-workbook per project (chosen in Part 1: one workbook per project,
  sheets = tables)
- Incremental/streaming profile (re-upload re-profiles the full workbook)
- User-supplied custom checks (a future "rules engine" - not part of MVP)
- Export of profile to CSV/PDF (could fit Part 6 if asked, currently not
  planned)
