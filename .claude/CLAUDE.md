# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Claude Setup (`.claude/`)

### Agents
Specialized sub-agents invoked automatically or via the Agent tool based on task context.

| Agent | File | When to use |
|-------|------|-------------|
| `spec-writer` | `agents/spec-writer.md` | Before any feature work — creates and scores spec files; refuses to write implementation code |
| `backend-dev` | `agents/backend-dev.md` | FastAPI endpoints, SQLAlchemy models, LLM provider work, pytest |
| `frontend-dev` | `agents/frontend-dev.md` | Next.js components, pages, Tailwind styling, Vitest/Playwright tests |
| `data-quality-specialist` | `agents/data-quality-specialist.md` | DQ pipeline modules — profiling, similarity, clustering, cross-table, normalization |
| `bcm-specialist` | `agents/bcm-specialist.md` | BCM domain — capability hierarchy, agent loop, Cytoscape graph, kanban UI |
| `test-runner` | `agents/test-runner.md` | Run tests and report results (Haiku model — fast) |
| `code-reviewer` | `agents/code-reviewer.md` | Review code changes for correctness, security, pattern consistency (Opus model) |

### Slash Commands
Invoked as `/command-name [arguments]` in the Claude Code prompt.

| Command | Arguments | Purpose |
|---------|-----------|---------|
| `/write-spec` | `<feature description>` | Create a numbered spec in `specs/`, self-score via SCORE, halt at SCORED for human approval |
| `/implement-spec` | `<NNN>` | Implement from an approved spec; refuses if not APPROVED or SCORE < 20/25 |
| `/score-spec` | `<NNN>` | Re-evaluate an existing spec's SCORE; list gaps; propose fixes |
| `/list-specs` | `[status]` | Table of all specs filtered by optional status |
| `/test-backend` | `[pytest args]` | Run backend pytest suite with optional filter |
| `/test-frontend` | `[e2e]` | Run Vitest unit tests or Playwright E2E |
| `/new-endpoint` | `<description>` | Scaffold a FastAPI endpoint following platform patterns |
| `/new-component` | `<description>` | Scaffold a React component with co-located test |
| `/dq-feature` | `<description>` | Add a DQ analysis step through the full pipeline |
| `/add-llm-tool` | `<description>` | Add a tool to the LLM agent tool set |
| `/review-changes` | `[commit/file]` | Review uncommitted or recent changes |

### Settings
`settings.json` pre-approves common safe commands (pytest, npm test/build, git read-only, uv, docker compose, uvicorn) so Claude does not prompt for permission on routine dev operations.

---

## Spec-Driven Development

**Rule: No spec. No code.** Every feature starts with a spec file. No implementation is written until a spec exists, is complete, and has passed its SCORE self-assessment (minimum 20/25).

### Workflow
```
/write-spec <feature description>   # Creates specs/NNN-title.md, self-scores, halts at SCORED
# Human reviews → sets status to APPROVED
/implement-spec <NNN>               # Implements backend first, then frontend, then runs tests
```

### Spec lifecycle
`DRAFT → SCORED → CONTRACT → APPROVED → IN_PROGRESS → DONE`

Spec is **locked at APPROVED** — no requirement changes after that. Scope changes require a new spec or an explicit amendment note.

### SCORE principle (minimum 20/25)
| Dimension | Min | What it enforces |
|-----------|-----|-----------------|
| S — Simple | 4/5 | Minimum viable solution; no future-proofing |
| C — Complete | 4/5 | All requirements and error states defined |
| O — Optimized | 3/5 | Lean API contract; no unused fields |
| R — Reviewable | 4/5 | Any dev can implement without asking questions |
| E — Executable | 4/5 | Every SHALL maps to a concrete, testable code action |

Spec files live in `specs/` — rules in `specs/RULES.md`, template in `specs/SPEC_TEMPLATE.md`.

---

## Dev Commands

### Full stack (Docker)
```bash
./scripts/start.sh      # Build and start all services
./scripts/stop.sh       # Stop all services
```

### Frontend (Next.js)
```bash
cd frontend
npm install
npm run dev             # Dev server at http://localhost:3000
npm run build
npm run test            # Vitest unit tests
npm run test:watch
npm run test:e2e        # Playwright E2E (requires running stack)
```

### Backend (FastAPI)
```bash
cd backend
uv sync                              # Install dependencies
uvicorn app.main:app --reload        # Dev server at http://localhost:8000
pytest                               # Full suite
pytest tests/test_auth.py            # Single file
pytest -k "test_name"                # Name filter
pytest tests/test_data_quality*.py   # All DQ tests
```

---

## Architecture

### Request Flow
All traffic enters through **Next.js on port 3000**. Requests to `/api/*` are proxied to the FastAPI backend (`BACKEND_URL` env var — `http://localhost:8000` in dev, `http://backend:8000` in Docker). No direct external access to the backend.

### Authentication
- Session-cookie (`dt_session`, httpOnly, SameSite=Lax); in-memory store; hardcoded `user` / `password`
- Auth gating in **server components** (`app/(app)/layout.tsx` → `getSessionUser()` → `GET /api/auth/me`), not middleware
- Invalid sessions redirect to `/login`

### Backend (`backend/app/`)
**BCM domain:** `bcm.py` — AI agent + CRUD for L1/L2/L3 capability hierarchy

**Data Quality domain (`data_quality/`):**
- `router.py` — all DQ endpoints (~45KB, the public surface)
- `profile.py`, `stats.py` — profiling and statistical analysis
- `normalize.py` — pre-similarity normalization (case, whitespace, unicode, phone/date parsers)
- `similarity.py` / `similarity_llm.py` — algorithmic and LLM-assisted similarity scoring
- `cluster.py`, `cross.py`, `annotator.py`, `recommend.py`, `agent.py` — clustering, referential checks, annotation, recommendations, DQ chat agent

**Shared:** `llm/` (Anthropic + OpenAI provider abstraction), `db.py` + `models.py` (SQLAlchemy 2.0 + SQLite), `files.py` (Excel/PDF upload), `threads.py` (conversation threads)

### Frontend (`frontend/`)
- App Router: `(app)/` auth-gated, `(auth)/` public
- TailwindCSS 4 with CSS custom property design tokens (see `frontend-dev` agent for full palette)
- Cytoscape.js (BCM graph), Plotly.js (DQ charts), @assistant-ui/react (chat), Radix UI (primitives)

### Database
SQLite at `{DT_DATA_DIR}/dt.db`, auto-created on startup, foreign keys enabled via PRAGMA. Persistent via Docker named volume `dt-data`. Schema in `docs/database.md`.

### LLM Integration
Both Anthropic and OpenAI supported via `app/llm/provider.py` abstraction. Tool definitions in Anthropic canonical format; `openai_provider.py` translates. AI annotation runs off the request thread.

---

## Coding Standards

1. **Simple over clever** — never over-engineer; no extra features beyond what was asked; no speculative abstractions
2. **Root cause first** — prove the root cause before attempting a fix; do not guess
3. **No emojis** — anywhere: code, comments, UI text, commit messages
4. **Latest idioms** — use current library APIs; avoid deprecated patterns

---

## Key Environment Variables
| Variable | Default | Description |
|---|---|---|
| `DT_DATA_DIR` | `backend/data/` | SQLite database directory |
| `BACKEND_URL` | `http://localhost:8000` | Frontend → backend proxy target |
