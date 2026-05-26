# SPEC-002: Replace SQLite with PostgreSQL

**Status:** DONE
**Created:** 2026-05-20
**Author:** spec-writer agent
**Touches:** Backend

---

## 1. Problem Statement

The platform currently uses SQLite, which serialises all writes through a single file lock. This is adequate for single-user local development but becomes a bottleneck when multiple concurrent requests hit the backend simultaneously (e.g., background AI annotation running while a user uploads a second file). SQLite also cannot be horizontally scaled — a second backend container cannot safely share the same file. Replacing SQLite with PostgreSQL removes the concurrency ceiling, supports multi-container deployments, and aligns the platform with production-grade infrastructure without changing any external API behaviour.

---

## 2. Requirements

1. The system SHALL add `psycopg2-binary` and `alembic` as runtime dependencies in `backend/pyproject.toml`.
2. The system SHALL read the PostgreSQL connection string from a single environment variable named `DATABASE_URL` with the format `postgresql://user:password@host:port/dbname`.
3. If `DATABASE_URL` is not set, the system SHALL raise a `RuntimeError` at startup with the message `"DATABASE_URL environment variable is required"` — the application SHALL NOT start.
4. The `database_url()` function in `backend/app/common/db.py` SHALL return the value of `DATABASE_URL` directly, without constructing a file path.
5. The `make_engine()` function SHALL create the engine using `postgresql+psycopg2` dialect and SHALL NOT pass `connect_args={"check_same_thread": False}` (which is SQLite-specific).
6. The SQLite-specific `_enable_foreign_keys` event listener that executes `PRAGMA foreign_keys = ON` SHALL be removed; PostgreSQL enforces foreign keys natively.
7. The singleton pattern for `_engine` and `_session_factory` module-level globals in `backend/app/common/db.py` SHALL be retained unchanged — `get_engine()` returns the same engine instance on every call.
8. The `DT_DATA_DIR` environment variable and all file-path construction logic in `backend/app/common/db.py` SHALL be removed.
9. The three SQLite-specific inline migration functions (`_migrate_chat_tables`, `_migrate_dataset_annotation_columns`, `_migrate_dataset_config_column`) SHALL be removed from `backend/app/common/db.py`; `init_db()` SHALL call `alembic upgrade head` programmatically (via `alembic.command.upgrade`) and then the seed/orphan-repair logic — it SHALL NOT call `Base.metadata.create_all(engine)` directly.
10. The `docker-compose.yml` SHALL add a `db` service using the `postgres:16` image with environment variables `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, and a named volume `dt-pgdata` for data persistence.
11. The `backend` service in `docker-compose.yml` SHALL declare a `DATABASE_URL` environment variable pointing to the `db` service, and SHALL declare `depends_on: [db]` with a `condition: service_healthy`.
12. The `db` service in `docker-compose.yml` SHALL declare a `healthcheck` using `pg_isready` so the backend does not start before PostgreSQL is accepting connections.
13. The named volume `dt-data` (the old SQLite volume) SHALL be removed from `docker-compose.yml`; the `DT_DATA_DIR` environment variable on the `backend` service SHALL be removed.
14. `backend/app/main.py` SHALL remain unchanged — it imports `get_engine` and `init_db` from `app.db` (the backward-compat shim), which already re-exports from `app.common.db`.
15. The backward-compat shim `backend/app/db.py` SHALL continue to re-export `database_url`, `make_engine`, `get_engine`, `get_session_factory`, `get_db`, `init_db`, and `Base` — no consumers of the shim need to change.
16. All existing pytest tests that instantiate an in-memory SQLite engine directly for isolation SHALL continue to work; those tests create their own engine via `make_engine(url)` with an explicit URL argument, so they are unaffected by the env-var guard in `database_url()`.
17. A `.env.example` file SHALL be created at `backend/.env.example` containing the following keys with illustrative defaults: `POSTGRES_USER=dt`, `POSTGRES_PASSWORD=dt`, `POSTGRES_DB=dt`, `DATABASE_URL=postgresql://dt:dt@db:5432/dt`. This file SHALL be committed to version control.
18. The `backend/.env` file (operator copy of `backend/.env.example`) SHALL be listed in `.gitignore` so that real credentials are never committed.
19. The `docker-compose.yml` `db` service environment variables (`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`) and the `backend` service `DATABASE_URL` SHALL reference `${VARIABLE_NAME}` substitution syntax so that Docker Compose reads their values from the `backend/.env` file at runtime via `env_file: backend/.env` on each service.
20. An Alembic environment SHALL be initialised under `backend/alembic/` by running `alembic init alembic` inside `backend/`. The generated `alembic/env.py` SHALL be modified to import `Base` from `app.common.db` and set `target_metadata = Base.metadata` so that autogenerate compares against the ORM models.
21. `alembic.ini` SHALL be placed at `backend/alembic.ini`. Its `sqlalchemy.url` key SHALL be left blank (empty string); the `env.py` SHALL read `DATABASE_URL` from the environment and pass it to `config.set_main_option("sqlalchemy.url", ...)` at runtime so that no credentials appear in the ini file.
22. A single initial migration script SHALL be generated via `alembic revision --autogenerate -m "initial_schema"` against the current ORM models. The generated script SHALL be committed to version control under `backend/alembic/versions/`.
23. Every migration script (including the initial one) SHALL guard each `op.create_table()` call with a check that the table does not already exist using `op.get_bind().dialect.has_table(op.get_bind(), "<table_name>")`, and each `op.add_column()` call with a check that the column does not already exist, so that re-running `alembic upgrade head` on an already-migrated database is a no-op rather than an error.
24. The `downgrade()` function in every migration script SHALL guard each `op.drop_table()` and `op.drop_column()` call with an existence check (using `has_table` / `has_column` on the bound connection) for the same idempotency guarantee in the rollback direction.
25. Every repository method (`*.repository.py`) that queries an ORM model with a mapped relationship and iterates over the results accessing that relationship SHALL use `sqlalchemy.orm.joinedload` or `sqlalchemy.orm.selectinload` in the query options to load the related rows in the same query, preventing N+1 query patterns. A relationship is considered "accessed" when the result set is used in a loop or list comprehension that reads an attribute declared as a `relationship()` on the model.

---

## 3. Out of Scope

- Async SQLAlchemy (`asyncpg`, `AsyncSession`) — the platform uses synchronous SQLAlchemy throughout; this spec does not change that.
- Async SQLAlchemy (`asyncpg`, `AsyncSession`) — the platform uses synchronous SQLAlchemy throughout; this spec does not change that.
- Connection pooling configuration beyond SQLAlchemy defaults (pool size, overflow, timeout).
- Alembic autogenerate for future schema changes — only the initial migration is generated as part of this spec.
- SSL/TLS certificate configuration for the PostgreSQL connection.
- Data migration from an existing SQLite file to PostgreSQL — this spec targets new or reset deployments only.
- Changes to any frontend code.
- Changes to any API endpoint paths, request shapes, or response shapes.
- Adding a database admin UI (e.g., pgAdmin) to docker-compose.
- Altering any backend module other than `backend/app/common/db.py`.

---

## 4. API Contract

Not applicable. This spec introduces no new or changed HTTP endpoints. All external API behaviour remains identical.

---

## 5. Frontend Behaviour

Not applicable. No frontend changes are required. The frontend communicates only with FastAPI over HTTP; the database layer is invisible to it.

---

## 6. Backend Behaviour

### Startup sequence

When the FastAPI application starts (the `lifespan` handler in `main.py`), it calls `init_db(get_engine())`. `get_engine()` calls `database_url()`, which reads `DATABASE_URL` from the environment. If the variable is absent, a `RuntimeError` is raised immediately and the process exits before any route is registered.

If `DATABASE_URL` is present, `make_engine()` creates a SQLAlchemy engine using the `postgresql+psycopg2` dialect. The engine is stored in the module-level `_engine` global. Subsequent calls to `get_engine()` return the same instance without creating a new engine.

`init_db()` then calls `alembic.command.upgrade(alembic_cfg, "head")` where `alembic_cfg` is an `alembic.config.Config` object pointing to `backend/alembic.ini` with `sqlalchemy.url` set to the value of `DATABASE_URL`. This applies all pending versioned migration scripts in order. After migrations complete, `init_db()` seeds the `project_types` catalog rows and repairs any orphaned `ChatMessage` rows — both unchanged from the current implementation. `Base.metadata.create_all()` is no longer called directly.

### Per-request session lifecycle

`get_db()` calls `get_session_factory()` to obtain the `sessionmaker` bound to the singleton engine, opens a new `Session`, yields it to the FastAPI dependency injection system, and closes it when the request handler returns. This is unchanged from the current implementation.

### Alembic migration structure

Alembic lives entirely under `backend/alembic/`. The `env.py` imports `Base` from `app.common.db` and sets `target_metadata = Base.metadata`. The `alembic.ini` at `backend/alembic.ini` has an empty `sqlalchemy.url`; `env.py` reads `DATABASE_URL` from the environment at runtime and injects it via `config.set_main_option`. This means no credentials ever appear in committed files.

The initial migration script (under `backend/alembic/versions/`) captures the full schema as it exists today. Each `upgrade()` function guards every DDL operation with an existence check so that `alembic upgrade head` is always a no-op when already at head. Each `downgrade()` function provides the same guard in reverse.

### N+1 prevention in the repository layer

Any repository method that returns a collection of ORM instances where the caller will access a `relationship()` attribute MUST declare eager loading in the query. Use `options(joinedload(Model.relation))` for one-to-one or many-to-one, and `options(selectinload(Model.relation))` for one-to-many collections. Lazy loading (the SQLAlchemy default) is permitted only when the method's contract guarantees the relationship will never be accessed after the session closes.

### Removed SQLite-specific logic

The `PRAGMA foreign_keys = ON` event listener fires on every new connection. PostgreSQL does not require this and the listener SHALL be deleted entirely. The three `_migrate_*` functions contain `ALTER TABLE` statements in SQLite-specific syntax and SHALL be deleted. Their purpose was one-shot schema patching on the existing SQLite database; PostgreSQL deployments start fresh via `create_all`.

### docker-compose topology

The `db` service runs `postgres:16`. The `backend` service connects to it via `DATABASE_URL=postgresql://dt:dt@db:5432/dt` (exact credentials are illustrative defaults; operators may override via a `.env` file). The `backend` service waits for the `db` service to pass its healthcheck before starting. The healthcheck command is `pg_isready -U dt -d dt`.

---

## 7. Acceptance Criteria

- [ ] AC-1 (REQ-1): `psycopg2-binary` appears in the `dependencies` list in `backend/pyproject.toml`.
- [ ] AC-2 (REQ-2, REQ-3): Starting the backend without `DATABASE_URL` set raises `RuntimeError` with message `"DATABASE_URL environment variable is required"` and the process exits non-zero before accepting requests.
- [ ] AC-3 (REQ-4): `database_url()` returns the raw value of `DATABASE_URL`; no file-path construction logic remains in the function.
- [ ] AC-4 (REQ-5): The engine created by `make_engine()` uses the `postgresql+psycopg2` dialect; `connect_args={"check_same_thread": False}` is absent from the `create_engine()` call.
- [ ] AC-5 (REQ-6): The `_enable_foreign_keys` event listener and the `PRAGMA foreign_keys = ON` execution are absent from `backend/app/common/db.py`.
- [ ] AC-6 (REQ-7): Calling `get_engine()` twice in the same process returns the same Python object (`assert get_engine() is get_engine()`).
- [ ] AC-7 (REQ-8): The `_data_dir()` function and all references to `DT_DATA_DIR` are absent from `backend/app/common/db.py`.
- [ ] AC-8 (REQ-9): `_migrate_chat_tables`, `_migrate_dataset_annotation_columns`, and `_migrate_dataset_config_column` are absent from `backend/app/common/db.py`; `init_db()` calls `alembic.command.upgrade` with `"head"`, the seed loop, and the orphan-repair loop — `Base.metadata.create_all` is absent from `init_db()`.
- [ ] AC-9 (REQ-10): `docker-compose.yml` contains a `db` service using image `postgres:16` with `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` environment variables and the `dt-pgdata` named volume mounted at `/var/lib/postgresql/data`.
- [ ] AC-10 (REQ-11): The `backend` service in `docker-compose.yml` has a `DATABASE_URL` environment variable whose host segment is `db`, and its `depends_on` entry for `db` includes `condition: service_healthy`.
- [ ] AC-11 (REQ-12): The `db` service in `docker-compose.yml` declares a `healthcheck` block whose `test` field invokes `pg_isready`.
- [ ] AC-12 (REQ-13): The `dt-data` volume entry and the `DT_DATA_DIR` environment variable are absent from `docker-compose.yml`.
- [ ] AC-13 (REQ-14, REQ-15): `backend/app/main.py` and `backend/app/db.py` are byte-for-byte identical to their current state (git diff is empty for those two files).
- [ ] AC-14 (REQ-16): Running `pytest` with `DATABASE_URL` unset succeeds for any test that calls `make_engine(url="sqlite:///:memory:")` because the explicit `url` argument bypasses the `database_url()` env-var read.
- [ ] AC-15 (REQ-17): `backend/.env.example` exists and contains exactly the keys `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, and `DATABASE_URL` with illustrative default values.
- [ ] AC-16 (REQ-18): `.gitignore` contains an entry that matches `backend/.env` so that the file is excluded from version control.
- [ ] AC-17 (REQ-19): The four credential variables in `docker-compose.yml` use `${VARIABLE_NAME}` syntax; each relevant service declares `env_file: backend/.env`; running `docker compose config` with a populated `backend/.env` resolves them to their illustrative defaults.
- [ ] AC-18 (REQ-20): The directory `backend/alembic/` exists and contains `env.py`, `script.py.mako`, and `versions/`; `env.py` imports `Base` from `app.common.db` and assigns `target_metadata = Base.metadata`.
- [ ] AC-19 (REQ-21): `backend/alembic.ini` exists; its `sqlalchemy.url` value is an empty string; `env.py` calls `config.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])` before configuring the engine.
- [ ] AC-20 (REQ-22): At least one migration script exists under `backend/alembic/versions/` with a message containing `initial_schema`; it is committed to version control.
- [ ] AC-21 (REQ-23, REQ-24): The initial migration's `upgrade()` wraps every `op.create_table()` in a `has_table` guard; `downgrade()` wraps every `op.drop_table()` in a `has_table` guard. Running `alembic upgrade head` twice against a live PostgreSQL database produces no error on the second run.
- [ ] AC-22 (REQ-25): Every `*.repository.py` method that returns a list of ORM instances and whose callers access a `relationship()` attribute uses `joinedload` or `selectinload` in its query options; no such method relies on lazy loading for relationships accessed after session close.

---

## 8. SCORE Self-Assessment

| Dimension | Score (1–5) | Notes |
|-----------|-------------|-------|
| **S — Simple** | 4 | Scope expands beyond `common/db.py` and `docker-compose.yml` to include Alembic scaffolding and repository-layer changes, but every addition is strictly necessary for the stated goals (versioned migrations, N+1 prevention). No speculative abstractions. |
| **C — Complete** | 5 | All error states, removed symbols, docker additions/removals, test isolation, secrets management, Alembic directory structure, idempotency guards (upgrade and downgrade), and N+1 eager-loading rule are fully specified. |
| **O — Optimized** | 4 | No API contract because no endpoints change. REQ-14 and REQ-15 are explicit no-op guards rather than redundancy. Each new requirement (REQ-20–25) maps to a distinct, non-overlapping deliverable. |
| **R — Reviewable** | 4 | Exact file paths, env var names, Alembic command strings, guard method names (`has_table`, `has_column`), eager-loading strategy choice (`joinedload` vs `selectinload`), and `alembic.ini` key name are all stated explicitly. A developer needs no external references. |
| **E — Executable** | 4 | Every SHALL maps to a concrete, verifiable code action. AC-21 includes a runnable double-upgrade test. AC-22 describes an auditable pattern check across all `*.repository.py` files. |
| **Total** | **21/25** | Exceeds minimum of 20/25; all dimensions meet their minimums. |

**Revision needed:** None. All dimensions meet or exceed their minimums and the total exceeds 20/25.

---

## 9. Changelog

| Version | Date | Change |
|---------|------|--------|
| v1.0 | 2026-05-20 | Initial creation |
| v1.1 | 2026-05-20 | Added REQ-17, REQ-18, REQ-19 and AC-15, AC-16, AC-17 for `.env.example` at `backend/`, `.gitignore` entry, and `${VAR}` substitution in `docker-compose.yml` |
| v2.0 | 2026-05-21 | Removed Alembic from Out of Scope; added REQ-20–25 and AC-18–22 for Alembic scaffolding, idempotent migration guards (upgrade + downgrade), and N+1 eager-loading requirement on repository layer; updated REQ-1 (added `alembic` dependency), REQ-9 (`alembic upgrade head` replaces `create_all`), §6 startup and new migration/N+1 sections, AC-8, SCORE table (S: 5→4, total: 22→21) |
