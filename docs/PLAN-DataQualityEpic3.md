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
- `TREE_VERSION = "1.0.0"` (added Part 6)

## Part 6 — US 3.7 Tree structure for similar records

Split into 6.1 (backend) and 6.2 (frontend) so each carries its own approval gate.

### Decisions
- Hierarchy basis: **semantic-type buckets** — Identifiers / Contact / Address / Dates / Numeric / Other.
- Root: **highest-weight important column** (ties → lowest mapping id, mirroring `_choose_blocking_mapping`). Other important columns appear in a first-tier "Important" group under the root.
- UI surface: **new "Tree" tab in the existing Cluster Detail modal** (Part 6.2).
- Interactivity: **golden-record selection per leaf**, persisted.
- Persistence model: **cluster fingerprint** = `sha256("a:<sorted_a_members>|b:<sorted_b_members>")`. Re-runs with identical members → same fingerprint → saved picks restored.
- Conflict rule: **distinct normalized values**. If the saved Normalizer collapses every member to a single key, no conflict — auto-pick the most-common raw form (lex tie-break).

### Part 6.1 — Backend (shipped)
- Schema: `data_quality_record_clusters.fingerprint VARCHAR(64)` (indexed by `(run_id, fingerprint)`); new table `data_quality_cluster_golden_values` keyed on `(dataset_id, cluster_fingerprint, column_name)`.
- Migration: `_migrate_cluster_fingerprint` in `db.py` adds the column and backfills any pre-existing cluster rows from their `a_members_json` + `b_members_json` so golden lookups don't silently miss legacy data.
- Engine: `cluster.py` writes fingerprint inline at cluster persist time; helper `cluster_fingerprint(a_members, b_members)` is exported so tests and the backfill share one source of truth.
- Pure builder: `app/data_quality/tree.py` — semantic-bucket assignment, variant collation, conflict detection, golden overlay. Stays DB-free; the router builds inputs.
- Endpoints (under the existing similarity router):
  - `GET .../clusters/{cid}/tree` — builds tree on the fly, overlays saved golden picks.
  - `PUT .../clusters/{cid}/tree/golden` — upsert by `(dataset, fingerprint, column_name)`; validates `chosen_value` against the leaf's actual variants.
  - `DELETE .../clusters/{cid}/tree/golden/{column}` — idempotent revert to auto-pick.
- Schemas: `DataQualityClusterTreeOut`, `DataQualityTreeGroupOut`, `DataQualityTreeLeafOut`, `DataQualityTreeVariantOut`, `DataQualityGoldenValueIn`.
- Tests in `test_data_quality_tree.py`: bucket assignment, root selection, normalization-collapse auto-pick, true-conflict surfacing, explicit-null override, fingerprint stability (order-insensitive, A/B-distinct, membership-sensitive), engine writes fingerprint inline, GET/PUT/DELETE round-trip, validation rejects unknown columns and values not in variants, **golden carries across re-runs**, fingerprint backfill on a legacy DB.
- Full suite: 378 passed.

### Part 6.2 — Frontend (shipped)
- `lib/api.ts`: `getClusterTree`, `setClusterGolden`, `clearClusterGolden` + types `DqClusterTree`, `DqTreeGroup`, `DqTreeLeaf`, `DqTreeVariant`, `DqTreeBucket`.
- New `DataQualityClusterTreeView.tsx`: header pill with root value + conflict counter ("3 of 5 conflicts resolved"); root rendered with a distinguishing border; collapsible `<details>` groups per semantic bucket with bucket glyph + leaf count; per-leaf renderer that switches between read-only (no conflict) and radio-group + custom-value input + Reset (conflict). Custom-value input does a client-side check against the leaf's variants before firing PUT so the user doesn't get a 400 round-trip. "Export merged record" button writes a client-side JSON of the merged record.
- Update `DataQualityClusterModal.tsx`: added `Members | Pair scores | Tree` tabs with role=tab + aria-selected; default tab is Members (preserves prior behavior). Tree tab mounts the view lazily so the existing members-fetch isn't blocked.
- Tests (`DataQualityClusterTreeView.test.tsx`, 6 cases): root + Contact + Other groups render from the fixture; conflict leaves show radios, auto-pick leaves don't; selecting a radio fires PUT with `{column_name, chosen_value}` and the counter updates; Reset fires DELETE; custom-input rejects values not in the variant set; GET errors surface via role=alert.
- Existing modal test (`DataQualitySimilarityTab.test.tsx`) updated to click into the Pair scores tab before asserting the pair-score chip.
- Full frontend suite: 76 passed (15 files). `npx next build` succeeds; `tsc --noEmit` clean.
