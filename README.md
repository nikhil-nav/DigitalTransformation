# DigitalTransformation

A platform combining **Business Capability Mapping (BCM)** and **Data Quality (DQ)** analysis, with LLM-assisted workflows throughout.

---

## Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js (App Router), TailwindCSS 4, Cytoscape.js, Plotly.js |
| Backend | FastAPI, SQLAlchemy 2.0, SQLite |
| LLM | Anthropic Claude / OpenAI (unified provider abstraction) |
| Infra | Docker Compose |

---

## Quick Start

```bash
./scripts/start.sh    # Build and start all services
./scripts/stop.sh     # Stop all services
```

- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- Default credentials: `user` / `password`

---

## Architecture

### Request Flow

All traffic enters through **Next.js on port 3000**. Requests to `/api/*` are proxied to the FastAPI backend (`BACKEND_URL` — `http://localhost:8000` in dev, `http://backend:8000` in Docker).

### Backend (`backend/app/`)

Follows a **modular layered architecture** — each domain is a package with five layers:

```
{module}/
  {module}.router.py      # FastAPI routes
  {module}.controller.py  # Request/response handling
  {module}.service.py     # Business logic
  {module}.repository.py  # Data access (SQLAlchemy)
  {module}.schemas.py     # Pydantic models
  {module}.models.py      # ORM models
```

**Modules:** `auth/`, `bcm/`, `files/`, `projects/`, `threads/`

**Data Quality (`data_quality/`):** layered handlers + `pipeline/` sub-package containing all analysis steps (profiling, normalization, similarity, clustering, cross-table checks, annotation, recommendations, DQ agent).

**Shared (`common/`):** `db.py`, `models.py`, `dependencies.py`, `exceptions.py`, `security.py`

**LLM (`llm/`):** unified Anthropic/OpenAI provider; tool definitions in Anthropic canonical format.

### Frontend (`frontend/`)

- App Router: `(app)/` auth-gated, `(auth)/` public
- TailwindCSS 4 with CSS custom property design tokens
- Cytoscape.js (BCM graph), Plotly.js (DQ charts), @assistant-ui/react (chat), Radix UI (primitives)

### Database

SQLite at `{DT_DATA_DIR}/dt.db`, auto-created on startup, foreign keys enforced via PRAGMA. Persistent via Docker named volume `dt-data`. Schema documented in `docs/database.md`.

---

## Dev Setup

### Backend

```bash
cd backend
uv sync                              # Install dependencies
uvicorn app.main:app --reload        # Dev server at http://localhost:8000
pytest                               # Full test suite
pytest tests/test_data_quality*.py   # DQ tests only
```

### Frontend

```bash
cd frontend
npm install
npm run dev             # Dev server at http://localhost:3000
npm run test            # Vitest unit tests
npm run test:e2e        # Playwright E2E (requires running stack)
```

---

## Key Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DT_DATA_DIR` | `backend/data/` | SQLite database directory |
| `BACKEND_URL` | `http://localhost:8000` | Frontend → backend proxy target |
