# Data Quality Epic 3 — Record-Level Similarity Scoring

A 5-part plan. The user must explicitly approve each completed part before
the next begins.

## Scope (confirmed with user)
- **Cross-sheet linkage only.** The user picks Sheet A and Sheet B, maps
  columns A.col ↔ B.col, and the engine returns clusters of matching records
  across the two sheets. Intra-sheet dedup is out of scope for this Epic.
- **Blocking gate before dashboard.** After upload, the existing DQ profile
  still runs in the background (so the dashboard is ready when needed), but
  the user lands on the new Profiling Setup & Configuration page first. A
  "Skip similarity" link lets them bypass the gate without running.
- **Heuristic recommender by default, "Improve with AI" button.** Per-column
  algorithm + per-column normalization is derived from the existing semantic
  type / pattern label / value-length stats. The LLM is opt-in and refines an
  existing recommendation; it never blocks the page.
- **Importance is a clustering criterion, not a scoring criterion.** A pair's
  similarity score is the weighted average across all mapped columns. A pair
  joins a cluster only when its similarity on every important column meets
  the threshold. Non-important columns are scored for display only. If no
  column is marked important, the run is rejected — never silently relaxed.

## Cross-cutting commitments (precision before speed)
- **Engine versioning.** `NORMALIZE_VERSION`, `SIMILARITY_VERSION`,
  `CLUSTER_VERSION`. Every persisted row records the engine version it was
  produced under; re-running with the same config + dataset is bit-stable.
- **Raw values are never mutated.** Normalization is computed on the fly;
  the cell value displayed to the user is always the original.
- **Parser failures are surfaced, never silently dropped.** A phone that
  fails E.164 parsing is retained as the original string with
  `parsed=False`; algorithms that need structured input (date proximity,
  phone exact) treat it as an unparseable mismatch and the pair is annotated
  rather than scored zero by accident.
- **No silent truncation.** Pair-cap default 100,000 per run; exceeding the
  cap rejects the run with a clear error so the user can tighten blocking or
  filter rows first.
- **Blocking is announced.** The default blocking key (first-3-chars +
  soundex on the heaviest text mapping) is shown in the UI; the user can see
  what was compared and what wasn't.
- **No silent relaxation of importance.** A run with zero important columns
  fails fast.

## Part 1 — Schema + normalization engine + field-specific parsers
- New tables (idempotent ALTER on startup):
  - `data_quality_profile_configs` — one per dataset; normalization toggles
    JSON, threshold, sheet_a, sheet_b, status, engine_version, timestamps.
  - `data_quality_column_mappings` — one row per A.col ↔ B.col pair;
    algorithm, weight (0..1), `is_important`, parser, `recommended_by`
    (`heuristic`|`llm`|`user`).
  - `DataQualityDataset.config_completed_at` (nullable) — drives the
    blocking-gate UX.
- `app/data_quality/normalize.py` — every US 3.2 rule as a pure fn
  (`case_fold`, `collapse_whitespace`, `strip_punctuation`, `nfkd_fold`,
  `strip_special_chars`, `strip_corporate_suffix`, `expand_address_abbrev`).
  `Normalizer(enabled_set).apply(value) -> str | None`.
- `app/data_quality/parsers.py` — `parse_phone_e164`, `parse_email`,
  `parse_date_iso`. Each returns `(value, ok)`.
- Tests:
  - One test per rule using the spec's exact example.
  - Hypothesis: applying any subset of rules to a value is idempotent on a
    second application.
  - Parser tests for the spec's exact examples.
- New deps: `rapidfuzz`, `phonenumbers`, `dateparser`, `jellyfish`,
  `unidecode`.

## Part 2 — Similarity algorithms + heuristic recommender + LLM hook
- `app/data_quality/similarity.py` — registry of all 7 algorithm families
  from US 3.4 (exact, Levenshtein/Jaro-Winkler, Jaccard, Cosine, Soundex,
  Metaphone, n-gram, numeric tolerance, date proximity). Each entry knows
  which semantic types it accepts.
- `app/data_quality/recommend.py` — rule-based recommender keyed on
  `(semantic_type_a, semantic_type_b, pattern_label, value-length stats)`.
  Also recommends a default mapping by pairing columns with name-similarity
  > 0.5.
- Tests: per-algorithm unit tests for known I/O; recommender tests for each
  semantic-type combination.
- LLM refinement (`POST /similarity/recommend-llm`) is deferred to Part 4
  where it joins the rest of the config CRUD endpoints (it refines an
  already-saved config and therefore depends on those endpoints).

## Part 3 — Clustering engine + run/config endpoints
- New tables: `data_quality_similarity_runs`, `data_quality_record_pairs`,
  `data_quality_record_clusters`.
- `app/data_quality/cluster.py`:
  - `block_candidates(df_a, df_b, mappings)` — blocking iterator.
  - `score_pair(...)` — per-column scores + weighted-average overall score.
  - `cluster_pairs(...)` — union-find on pairs whose important-column
    scores exceed the threshold.
  - `run_similarity(...)` — orchestrator.
- Endpoints (config CRUD ships here because run depends on it):
  - `GET /similarity/config` — return saved config; if none yet, return the
    heuristic recommendation as a draft.
  - `PUT /similarity/config` — upsert config + mappings (validates that at
    least one important column is set; rejects the save otherwise so an
    invalid config can never be saved and then fail at run-time).
  - `POST /similarity/run` — execute; persists run + clusters + pairs.
  - `GET /similarity/runs` — list runs.
  - `GET /similarity/runs/{id}/clusters` — list clusters with members +
    per-pair scores.
  - `POST /similarity/skip` — sets `config_completed_at` without running,
    so the user can opt out of the gate.
- Tests: planted-match fixture, threshold sweep, blocking-recall test,
  pair-cap enforcement, end-to-end via HTTP.

## Part 4 — Frontend config page (US 3.1–3.4)
- `DataQualityConfigPage.tsx`:
  - Step 1: pick Sheet A + Sheet B.
  - Step 2: normalization toggles with the spec's example as helper text.
  - Step 3: column-mapping table (A col / B col / algorithm / weight /
    important / parser). "Auto-map" + "Improve with AI" buttons.
  - Step 4: threshold slider (default 0.85) + "Save & Run".
- `DataQualitySection` checks `config_completed_at` and mounts the config
  page when null. "Skip similarity" sets the flag without running.
- API types and helpers in `lib/api.ts`.
- Tests: render, auto-map populates rows, weight clamps, important toggle
  persists.

## Part 5 — Clusters on dashboard (US 3.5–3.6) + tests
- New "Similarity" tab in `DataQualityDashboard` alongside Sheets and
  Cross-table.
- Tab contents: last-run summary, clusters table (canonical key from
  important columns, size, top/min score), cluster-detail modal with
  members from both sheets, normalized previews, per-column score breakdown.
- "Edit config" → config page; "Re-run" → new run.
- Tests: dashboard mock with one run + several clusters; modal open/close;
  recall after re-run.

## Engine versions
- `NORMALIZE_VERSION = "1.0.0"`
- `SIMILARITY_VERSION = "1.0.0"`
- `CLUSTER_VERSION = "1.0.0"`
