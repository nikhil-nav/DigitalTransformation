# Backend

FastAPI backend for the Digital Transformation Platform.

## Requirements

- Python 3.12+
- PostgreSQL 16+
- [uv](https://docs.astral.sh/uv/) for dependency management

## Setup

```bash
# Install dependencies
uv sync

# Copy and edit environment variables
cp .env.example .env
# Edit .env and set DATABASE_URL to your PostgreSQL connection string
```

## Running

```bash
uvicorn app.main:app --reload
```

API available at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

## Environment Variables

| Variable | Description |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string — `postgresql://user:password@host:5432/dbname` |

Copy `.env.example` to `.env` and fill in the values. The app loads `.env` automatically on startup.

## Database Migrations (Alembic)

Migrations live in `alembic/versions/`. The app runs `alembic upgrade head` automatically on startup via `init_db()`.

```bash
# Apply all pending migrations to head
alembic upgrade head

# Roll back the last migration
alembic downgrade -1

# Roll back all migrations
alembic downgrade base

# Show current migration revision
alembic current

# Show migration history
alembic history --verbose

# Show pending migrations (not yet applied)
alembic history -r current:head

# Generate a new migration from ORM model changes
alembic revision --autogenerate -m "describe_your_change"

# Generate a blank migration (for manual SQL)
alembic revision -m "describe_your_change"

# Show the SQL that would be executed (dry run)
alembic upgrade head --sql

# Stamp the database at a specific revision without running migrations
alembic stamp head
alembic stamp <revision_id>
```

> Alembic reads `DATABASE_URL` from the environment (or `.env`). Run all commands from the `backend/` directory where `alembic.ini` lives.

## Testing

```bash
# Run full test suite
pytest

# Run a single file
pytest tests/test_auth.py

# Run by name filter
pytest -k "test_name"

# Run all data quality tests
pytest tests/test_data_quality*.py

# Run with output (no capture)
pytest -s

# Run with verbose output
pytest -v
```

Tests use an in-memory SQLite database and do not require `DATABASE_URL` to be set.

## Dependency Management

```bash
# Install all dependencies (including dev)
uv sync

# Add a runtime dependency
uv add <package>

# Add a dev-only dependency
uv add --dev <package>

# Remove a dependency
uv remove <package>

# Upgrade all dependencies
uv sync --upgrade
```
