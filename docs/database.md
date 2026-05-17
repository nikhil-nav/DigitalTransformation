# Database

This document is the architecture spec for the SQLite database. The authoritative schema definition lives in [`db-schema.json`](db-schema.json); this file explains the *why* and answers the operational questions.

## Storage and location

- **Engine:** SQLite (single file).
- **Container path:** `/app/data/dt.db`.
- **Host persistence:** the `dt-data` named Docker volume (defined in `docker-compose.yml`) is mounted at `/app/data`, so the DB survives container rebuilds and `docker compose down`/`up` cycles.
- **Local dev (no Docker):** the path is taken from the `DT_DATA_DIR` environment variable, defaulting to a `data/` directory beside the backend project (`backend/data/dt.db`).
- **Connection settings:** `PRAGMA foreign_keys = ON` is set on every new connection so cascade/restrict rules in the schema actually fire.

## Creation on first run

On backend startup:

1. The application resolves the DB path from `DT_DATA_DIR`.
2. If the parent directory does not exist, it is created.
3. SQLAlchemy's `Base.metadata.create_all(engine)` runs — this is idempotent and only creates tables that are missing.
4. A small idempotent seeder inserts the four `project_types` rows (`value_discovery` active; the other three inactive). Existing rows are not touched, so re-running on an existing DB is a no-op.

This means the very first `docker compose up` produces a working DB with the seed data, and subsequent restarts make no changes.

## Schema overview

Four tables; see [`db-schema.json`](db-schema.json) for full column definitions.

```
users (1) --- (N) projects (N) --- (1) project_types
                     |
                     | (1)
                     v
                    (N)
        value_discovery_opportunities
```

- `users` — provisioned on demand. When the hardcoded `user` logs in, the auth layer looks up or creates the matching row.
- `project_types` — catalog table, seeded. Only `value_discovery` is `is_active = 1` for the MVP.
- `projects` — every project carries a `user_id` (owner) and `project_type_id`. Indexed on `user_id` for the list view; composite index on `(user_id, project_type_id)` for type-filtered lists.
- `value_discovery_opportunities` — child entity of a Value Discovery `projects` row. `ON DELETE CASCADE`, so deleting a project removes its opportunities.

## Multi-user isolation

- Every row that belongs to a user reaches it via a `user_id` FK on `projects` (and transitively on `value_discovery_opportunities` through `project_id`).
- The FK ensures referential integrity. Isolation itself — i.e. "user A cannot see user B's projects" — is enforced in the **query layer**: every read/write of `projects` and `value_discovery_opportunities` is scoped by the authenticated user's id, derived from the session in Part 4.
- This is tested in Part 6 with a "cross-user 404" test (request a project owned by another user, expect 404).

## Migration approach

For the MVP we use the simplest approach that is honest about what we have:

- **First run:** `create_all()` builds the schema.
- **Additive changes** (new table, new nullable column): add to the SQLAlchemy models; `create_all()` picks it up on next start.
- **Destructive changes** (rename, drop, type change, NOT NULL on existing column): not handled. The MVP path is to delete the DB file (or the `dt-data` volume) and re-run; only seed data and any locally-created projects are lost.
- **When this stops being acceptable:** introduce Alembic, generate an initial revision from the current schema, and require migrations for every subsequent change. The trigger is the first time we ship a schema change to a user with data we cannot reset.

## Open questions

- **Value Discovery payload shape.** The current proposal models the payload as one child table (`value_discovery_opportunities`). Two alternatives, called out so we can choose deliberately:
  - **JSON blob** on `projects.payload TEXT`. Simpler if Value Discovery fields are still in flux; loses queryability and FK enforcement. Recommended only if the user expects significant schema churn before Part 7.
  - **Wider relational model** (separate `value_discovery_details` table for top-level metadata, plus child tables for stakeholders, processes, future-state notes, etc.). Better long-term but more to build now.
- **`status` enums** are stored as `TEXT` with an in-app whitelist rather than a `CHECK` constraint. Easy to relax later; if we want DB-level enforcement now, we can add `CHECK (status IN (...))`.
- **Soft delete.** Not modelled. `DELETE` is a hard delete. Add a `deleted_at` column if/when soft delete becomes a requirement.

## Sign-off needed before Part 6

Confirm or push back on:

1. Schema shape — is the four-table model right, or should the Value Discovery payload be a JSON blob / wider relational set?
2. Field names and types on `projects` and `value_discovery_opportunities` — particularly the `effort`, `priority`, and `status` text enums.
3. Migration approach — `create_all()` only, with an explicit "delete the volume" path for breaking changes, until we earn the right to Alembic.
