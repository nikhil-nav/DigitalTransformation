# SPEC-001: Modular Layered Architecture Refactor (Backend)

**Status:** APPROVED
**Created:** 2026-05-19
**Author:** spec-writer agent
**Touches:** Backend

---

## 1. Problem Statement

The current FastAPI backend is organised as a flat collection of files (`auth.py`, `bcm.py`, `files.py`, `threads.py`, `projects.py`, `models.py`, `schemas.py`, `db.py`) alongside a single monolithic `data_quality/router.py` (~2000 lines). All concerns — routing, business logic, and database access — are mixed in the same file, and cross-domain models/schemas live in two god-files (`models.py`, `schemas.py`). This makes it hard to reason about any individual domain, difficult to test in isolation, and expensive to onboard new contributors. The codebase needs a consistent, layered module structure where every domain owns its routes, controller, service, repository, models, and schemas, and shared infrastructure lives in a single `common/` package.

---

## 2. Requirements

1. The system SHALL be restructured so that each domain (`auth`, `projects`, `bcm`, `files`, `threads`, `data_quality`) becomes a self-contained package under `backend/app/` with the layout: `router.py`, `controller.py`, `service.py`, `repository.py`, `models.py`, `schemas.py`.
2. The `router.py` in each module SHALL only contain FastAPI route decorators and calls to controller functions — no business logic, no DB queries.
3. The `controller.py` in each module SHALL parse the incoming request, call service functions, and format the HTTP response (status codes, headers) — no direct DB access.
4. The `service.py` in each module SHALL contain all business logic, call repository functions, and have no knowledge of HTTP (no `Request`, `Response`, `HTTPException` imports).
5. The `repository.py` in each module SHALL contain all SQLAlchemy ORM queries for that domain — no business logic and no HTTP knowledge.
6. The system SHALL create a `backend/app/common/` package containing: `db.py` (engine, session factory, `get_db` dependency), `dependencies.py` (shared FastAPI dependencies: `get_session_user`, `require_session_user`), `exceptions.py` (shared domain exception base classes), and `security.py` (cookie/session helpers currently in `auth.py`).
7. Domain-specific ORM models SHALL be moved from the monolithic `models.py` into the owning module's `models.py`; `common/models.py` SHALL contain only `Base` and any abstract mixin classes.
8. Domain-specific Pydantic schemas SHALL be moved from the monolithic `schemas.py` into the owning module's `schemas.py`; `common/schemas.py` SHALL be deleted or left empty when all schemas are distributed.
9. The `data_quality/` module SHALL keep its existing pipeline sub-modules (`profile.py`, `stats.py`, `cluster.py`, `similarity.py`, `similarity_llm.py`, `normalize.py`, `recommend.py`, `annotator.py`, `cross.py`, `inspect.py`, `parsers.py`, `agent.py`) under a `data_quality/pipeline/` sub-package; the monolithic `data_quality/router.py` SHALL be split into `router.py`, `controller.py`, `service.py`, `repository.py`, `models.py`, `schemas.py` following the same pattern as every other module.
10. The `llm/` package SHALL remain structurally unchanged (it is already well-layered); only its import paths SHALL be updated if moved.
11. The `backend/app/main.py` SHALL register routers by importing from each module's `router.py` only — no domain logic in `main.py`.
12. All existing HTTP endpoints SHALL remain at the same URL paths with the same request/response shapes — the external API contract SHALL NOT change.
13. All existing pytest tests SHALL pass without modification to test code after the refactor.
14. The system SHALL add a `backend/app/common/__init__.py` and each new module `__init__.py` so Python treats them as packages.
15. Circular imports SHALL be prevented by enforcing the dependency direction: `router → controller → service → repository`; modules MAY import from `common/` but SHALL NOT import from sibling modules' non-`schemas` layers.

---

## 3. Out of Scope

- Adding new API endpoints or changing existing endpoint behaviour.
- Changing the database schema, migrations, or SQLite setup.
- Frontend changes of any kind.
- Switching from SQLite to another database.
- Changing authentication from hardcoded credentials to a real auth system.
- Adding new tests (existing tests must pass; no new test files are required).
- Refactoring the `llm/` package internals beyond updating import paths.
- Splitting `data_quality/pipeline/` sub-modules further or changing their logic.
- Performance optimisations, caching, or async database access.
- Docker / environment variable changes.

---

## 4. API Contract

No new or changed endpoints. All existing routes stay at their current paths with identical request/response shapes. This section is intentionally omitted — the refactor is internal-only.

---

## 5. Frontend Behaviour

No frontend changes. The frontend calls the same URLs with the same payloads and receives the same responses after the refactor.

---

## 6. Backend Behaviour

### Target directory layout

```
backend/app/
├── main.py                          # Registers routers only
├── common/
│   ├── __init__.py                  # re-exports: db, Base, get_db, get_session_user, etc.
│   ├── common.db.py                 # Engine, SessionLocal, get_db dependency
│   ├── common.models.py             # Base, abstract mixins only
│   ├── common.dependencies.py       # get_session_user, require_session_user, get_llm_keys
│   ├── common.exceptions.py         # NotFoundError, UnauthorizedError (domain-agnostic)
│   └── common.security.py           # Cookie/session helpers
├── auth/
│   ├── __init__.py                  # re-exports: router, AuthService, AuthRepository, schemas
│   ├── auth.router.py               # POST /api/auth/login, POST /api/auth/logout, GET /api/auth/me, PUT /api/auth/llm-keys
│   ├── auth.controller.py
│   ├── auth.service.py
│   ├── auth.repository.py
│   ├── auth.models.py               # (empty or User model if stored in DB)
│   └── auth.schemas.py              # LoginRequest, MeResponse, LlmKeysRequest
├── projects/
│   ├── __init__.py                  # re-exports: router, ProjectService, ProjectRepository, schemas
│   ├── projects.router.py           # CRUD /api/projects/*, /api/project-types/*
│   ├── projects.controller.py
│   ├── projects.service.py
│   ├── projects.repository.py
│   ├── projects.models.py           # Project, ProjectType, ValueDiscoveryOpportunity
│   └── projects.schemas.py          # ProjectCreate, ProjectUpdate, ProjectResponse, etc.
├── bcm/
│   ├── __init__.py                  # re-exports: router, BcmService, BcmRepository, schemas
│   ├── bcm.router.py                # /api/projects/{id}/capabilities/*, /api/projects/{id}/chat/*
│   ├── bcm.controller.py
│   ├── bcm.service.py
│   ├── bcm.repository.py
│   ├── bcm.models.py                # BcmCapability, BcmFile
│   └── bcm.schemas.py               # CapabilityCreate, CapabilityResponse, ChatRequest, etc.
├── files/
│   ├── __init__.py                  # re-exports: router, FilesService, FilesRepository, schemas
│   ├── files.router.py              # GET/POST/DELETE /api/projects/{id}/files/*
│   ├── files.controller.py
│   ├── files.service.py
│   ├── files.repository.py
│   ├── files.models.py              # FileUploadRecord (file upload metadata only; BcmFile stays in bcm/bcm.models.py)
│   └── files.schemas.py             # FileResponse
├── threads/
│   ├── __init__.py                  # re-exports: router, ThreadsService, ThreadsRepository, schemas
│   ├── threads.router.py            # CRUD /api/projects/{id}/threads/*
│   ├── threads.controller.py
│   ├── threads.service.py
│   ├── threads.repository.py
│   ├── threads.models.py            # ChatThread, ChatMessage
│   └── threads.schemas.py           # ThreadCreate, ThreadResponse, MessageResponse
├── data_quality/
│   ├── __init__.py                  # re-exports: router, DqService, DqRepository, schemas
│   ├── data_quality.router.py       # All /api/projects/{id}/data-quality/* route decorators
│   ├── data_quality.controller.py   # HTTP parsing, response formatting
│   ├── data_quality.service.py      # Orchestrates pipeline calls
│   ├── data_quality.repository.py   # All DQ ORM queries
│   ├── data_quality.models.py       # All DataQuality* ORM models
│   ├── data_quality.schemas.py      # All DQ Pydantic schemas
│   └── pipeline/
│       ├── __init__.py
│       ├── agent.py
│       ├── annotator.py
│       ├── cluster.py
│       ├── cross.py
│       ├── inspect.py
│       ├── normalize.py
│       ├── parsers.py
│       ├── profile.py
│       ├── recommend.py
│       ├── similarity.py
│       ├── similarity_llm.py
│       └── stats.py
└── llm/
    ├── __init__.py
    ├── provider.py
    ├── anthropic_provider.py
    ├── openai_provider.py
    ├── session.py
    ├── agent.py
    └── tools.py
```

### `__init__.py` re-export pattern

Each module's `__init__.py` re-exports the public surface so callers use clean import paths instead of referencing dot-named files directly:

```python
# auth/__init__.py
from importlib import import_module as _im

_router_mod    = _im("app.auth.auth.router")
_service_mod   = _im("app.auth.auth.service")
_repo_mod      = _im("app.auth.auth.repository")
_schemas_mod   = _im("app.auth.auth.schemas")

router         = _router_mod.router
AuthService    = _service_mod.AuthService
AuthRepository = _repo_mod.AuthRepository
schemas        = _schemas_mod
```

Consumers import from the package, never from the dot-named file directly:

```python
# main.py
from app.auth import router as auth_router

# auth.controller.py (internal, may import sibling via importlib or relative)
from app.auth import AuthService
```

### Layer responsibilities (enforced by convention)

| Layer | Imports allowed | Imports forbidden |
|-------|----------------|-------------------|
| `router.py` | FastAPI, own `controller.py`, `common/dependencies.py` | `service.py`, `repository.py`, ORM models |
| `controller.py` | own `service.py`, own `schemas.py`, FastAPI (`HTTPException`, `status`) | `repository.py`, SQLAlchemy sessions directly |
| `service.py` | own `repository.py`, own `schemas.py`, `common/exceptions.py`, `llm/` | FastAPI, `HTTPException`, `Request`, `Response` |
| `repository.py` | SQLAlchemy, own `models.py`, `common/db.py` | FastAPI, `schemas.py`, `service.py` |

### Migration steps (implementation order)

1. Create `common/` package with `db.py`, `models.py` (Base only), `dependencies.py`, `exceptions.py`, `security.py` extracted from current `db.py` and `auth.py`.
2. Create each module package skeleton (`__init__.py` files).
3. Migrate `auth` module: move routes from `auth.py` → split into layers; move schemas.
4. Migrate `projects` module: extract `Project`, `ProjectType`, `ValueDiscoveryOpportunity` models + schemas.
5. Migrate `threads` module: extract `ChatThread`, `ChatMessage` models + schemas.
6. Migrate `files` module: extract `BcmFile` model + schemas.
7. Migrate `bcm` module: extract `BcmCapability` model + schemas; keep `llm/tools.py` in place.
8. Migrate `data_quality` module: move pipeline files to `pipeline/` sub-package; split router into layers; extract all DQ models + schemas.
9. Delete the old flat files (`auth.py`, `bcm.py`, `files.py`, `threads.py`, `projects.py`) and the monolithic `models.py`, `schemas.py`, `db.py`.
10. Update `main.py` to import routers from module packages.
11. Run full pytest suite; fix any import errors.

---

## 7. Acceptance Criteria

- [ ] AC-1: `backend/app/common/` package exists with `db.py`, `models.py`, `dependencies.py`, `exceptions.py`, `security.py`.
- [ ] AC-2: Each of `auth/`, `projects/`, `bcm/`, `files/`, `threads/`, `data_quality/` is a package containing dot-named layer files (`{module}.router.py`, `{module}.controller.py`, `{module}.service.py`, `{module}.repository.py`, `{module}.models.py`, `{module}.schemas.py`) and an `__init__.py` that re-exports the public surface (`router`, `*Service`, `*Repository`, `schemas`).
- [ ] AC-3: `data_quality/pipeline/` sub-package contains all 12 existing pipeline modules unchanged.
- [ ] AC-4: `main.py` contains only router imports and app setup — no business logic, no direct DB access.
- [ ] AC-5: No `router.py` file imports from SQLAlchemy or calls repository functions directly.
- [ ] AC-6: No `service.py` file imports `HTTPException`, `Request`, or `Response` from FastAPI.
- [ ] AC-7: No `repository.py` file imports from FastAPI or calls service functions.
- [ ] AC-7b: No `controller.py` file imports SQLAlchemy sessions or ORM models directly.
- [ ] AC-8: The old flat files (`auth.py`, `bcm.py`, `files.py`, `threads.py`, `projects.py`, top-level `models.py`, `schemas.py`, `db.py`) are deleted.
- [ ] AC-9: `pytest` exits 0 with all tests passing (no test file modifications required).
- [ ] AC-10: `GET /api/health`, all `/api/auth/*`, `/api/projects/*`, `/api/projects/{id}/capabilities/*`, `/api/projects/{id}/chat/*`, `/api/projects/{id}/files/*`, `/api/projects/{id}/threads/*`, and `/api/projects/{id}/data-quality/*` routes respond with the same status codes and response shapes as before.
- [ ] AC-11: `uvicorn app.main:app --reload` starts without import errors.
- [ ] AC-12: No circular imports exist (verified by `python -c "import app.main"`).

---

## 8. SCORE Self-Assessment

| Dimension | Score (1–5) | Notes |
|-----------|-------------|-------|
| **S — Simple** | 5 | Pure structural refactor; zero new logic, zero new endpoints, zero schema changes |
| **C — Complete** | 4 | All modules specified; migration order defined; all ACs are testable; the only gap is that `BcmFile` ownership (bcm vs files module) is noted but left to implementer since both are plausible |
| **O — Optimized** | 5 | No API contract section needed (no endpoint changes); directory layout is the contract |
| **R — Reviewable** | 4 | Any Python dev can implement from the layer responsibility table and directory layout; the migration step list removes ambiguity |
| **E — Executable** | 4 | REQ-3 controller DB isolation now covered by AC-7b; AC-8 updated to include `db.py` deletion |
| **Total** | **22/25** | Passes minimum (20/25) |

**Revision needed:** None. Score exceeds minimum on all dimensions.

---

## 9. Changelog

| Version | Date | Change |
|---------|------|--------|
| v1.0 | 2026-05-19 | Initial creation |
| v1.1 | 2026-05-19 | Added §9 Changelog section per versioning rule added to RULES.md |
| v1.2 | 2026-05-19 | Changed file naming convention to `{module}.layer.py` (e.g. `auth.controller.py`); added `__init__.py` re-export pattern; updated AC-2 |
| v1.3 | 2026-05-19 | Resolved BcmFile ownership to bcm module; added AC-7b (controller DB isolation); added db.py to AC-8 deletion list; E score revised 5→4, total 23→22 |
| v1.4 | 2026-05-19 | Status set to APPROVED by @nikhilyadav |
