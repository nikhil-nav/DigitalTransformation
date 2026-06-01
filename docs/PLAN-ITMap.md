# IT Map Agent — Implementation Plan

A 5-part plan. The user must explicitly approve each completed part before
the next begins.

## Scope (confirmed with user)
- **Lives on Value Discovery projects** alongside the existing BCM
  section — same project_id, BCM is right there to map against.
- **Flexible Excel schema** — agent reads the workbook and infers which
  columns hold name / description / business-function / tech-stack /
  owner / criticality.
- **Many-to-many mapping** — one application can map to multiple L2
  capabilities, each with its own confidence + rationale.
- **Suggest-then-confirm** — agent proposes mappings with
  `status='suggested'`; user reviews on the kanban with Confirm /
  Dismiss / Reassign (same pattern as DQ relationships).
- **L2-only mapping targets** — agent's `list_capabilities` returns
  `level=2` nodes by default.
- **Single-sheet inventories** — if a multi-sheet xlsx arrives, the
  largest sheet by row count is processed and the others are surfaced
  but ignored.

## Cross-cutting commitments (precision before speed)
- **Engine versioning** on every persisted row
  (`IT_MAP_AGENT_VERSION = "1.0.0"`, `IT_MAP_INVENTORY_VERSION = "1.0.0"`).
- **Re-runs preserve user decisions** — confirmed mappings stay
  confirmed, dismissed mappings stay dismissed, the agent cannot
  un-confirm or re-propose them.
- **Every mapping carries a non-empty rationale** — `propose_mapping`
  refuses to record without one.
- **Schema inference is an explicit, persisted step** — the user can
  inspect (and later override) what the agent decided each column means.
- **Tool-call cap per run** (`MAX_TOOL_CALLS_PER_RUN = 200`) so a
  runaway LLM loop fails fast.
- **Unmappable rows surface, not vanish** — appear in an "Unmapped"
  bucket with the agent's reason.
- **Background-task execution** — `POST /run` returns immediately with
  `status='running'`; UI polls. Same pattern as AI annotation.

## Part 1 — Schema + upload + Excel inspect (no agent yet)
- New table: `ApplicationInventory` — one per uploaded xlsx
  (project_id, original_filename, file_sha256, local_path, size_bytes,
  sheets_json, primary_sheet, engine_version, uploaded_at).
- Reuse `app/data_quality/inspect.py` for parsing.
- 3 endpoints, gated to `value_discovery` project type:
  - `POST /api/projects/{p}/it-map/inventories` — upload + inspect.
  - `GET /api/projects/{p}/it-map/inventories` — list.
  - `DELETE /api/projects/{p}/it-map/inventories/{id}` — cleanup file +
    DB row.
- Tests: gating, dedup on sha256, multi-sheet picks the largest.

## Part 2 — IT Map Agent (tools + dispatch + system prompt)
- New table: `ApplicationInventorySchema` — agent's persisted column-role
  inference (one row per inventory).
- New module `app/it_map/agent.py`:
  - Tools: `describe_inventory`, `read_sample(n=10)`, `read_row`,
    `list_capabilities(level=2)`, `propose_schema`, `propose_mapping`,
    `propose_unmappable`.
  - `MAX_TOOL_CALLS_PER_RUN = 200`.
  - Dispatch closure pattern (like DQ agent).
- Tests: every tool's contract + dispatch returns tool-error strings on
  bad input (not exceptions).

## Part 3 — Agent run as background task + persistence
- New tables: `Application` (one per extracted row),
  `ApplicationCapabilityMapping` (many-to-many to bcm_capabilities),
  `ITMapAgentRun` (audit per execution).
- `POST /it-map/inventories/{id}/run` — creates run row with
  `status='running'`, schedules `BackgroundTasks.add_task`, returns
  immediately. Engine bound via `db.get_bind()`.
- Re-run preserves user-confirmed and user-dismissed mappings; only
  suggested mappings from prior runs are replaced.
- 400 if no LLM key in session.
- Tests: end-to-end with mocked LLM; re-run preserves user decisions;
  tool-call cap rejects loudly.

## Part 4 — Frontend: upload + run + status
- New component `ITMapSection.tsx`, mounted alongside BCM section on
  Value Discovery project pages.
- Inventory list + Run agent button + run-status badge with 5s polling
  while any run is `running` (same pattern as AI annotation).
- API types + helpers in `lib/api.ts`.
- Tests: render, upload, run trigger, polling start/stop.

## Part 5 — Kanban + drawer + confirm / dismiss / reassign
- `ITMapKanban.tsx` — columns = L2 capabilities (+ "Unmapped"),
  cards = applications (appear in every column they map to).
- `ITMapAppDrawer.tsx` — raw row + inferred schema + all proposed
  mappings with per-mapping Confirm / Dismiss / Reassign buttons.
- 3 endpoints: `PATCH /it-map/mappings/{id}`,
  `POST /it-map/mappings` (user-driven reassign creates a new
  user-sourced mapping), `GET /it-map/applications/{id}`.
- Tests: render, confirm flip, reassign flow, kanban placement.

## Engine versions
- `IT_MAP_INVENTORY_VERSION = "1.0.0"` (Part 1)
- `IT_MAP_AGENT_VERSION = "1.0.0"` (Part 2)
