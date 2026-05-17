import os
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def _data_dir() -> Path:
    return Path(os.environ.get("DT_DATA_DIR", str(Path(__file__).parent.parent / "data")))


def database_url() -> str:
    d = _data_dir()
    d.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{(d / 'dt.db').as_posix()}"


@event.listens_for(Engine, "connect")
def _enable_foreign_keys(dbapi_connection, _connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.close()


def make_engine(url: str | None = None) -> Engine:
    return create_engine(
        url or database_url(),
        connect_args={"check_same_thread": False},
        future=True,
    )


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = make_engine()
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            autocommit=False, autoflush=False, bind=get_engine()
        )
    return _session_factory


def get_db() -> Generator[Session, None, None]:
    factory = get_session_factory()
    db = factory()
    try:
        yield db
    finally:
        db.close()


PROJECT_TYPE_SEED = [
    {"code": "value_discovery", "name": "Value Discovery", "is_active": True},
    {"code": "business_process_discovery", "name": "Business Process Discovery", "is_active": False},
    {"code": "ai_assessment", "name": "AI Assessment", "is_active": False},
    {"code": "data_quality_assessment", "name": "Data Quality Assessment", "is_active": True},
]


def _migrate_chat_tables(engine: Engine) -> None:
    """One-shot SQLite migration: bcm_chat_threads/messages -> chat_threads/messages.

    Adds a `scope` column populated to 'bcm' so existing BCM data is preserved
    untouched. Idempotent: safe to run on a fresh DB or one already migrated.
    SQLite (3.26+) updates FK references automatically on RENAME, so the
    chat_messages.thread_id FK continues to point at chat_threads.id.
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        if "bcm_chat_threads" in existing_tables and "chat_threads" not in existing_tables:
            conn.execute(text("ALTER TABLE bcm_chat_threads RENAME TO chat_threads"))
            conn.execute(
                text("ALTER TABLE chat_threads ADD COLUMN scope VARCHAR NOT NULL DEFAULT 'bcm'")
            )

        if "bcm_chat_messages" in existing_tables and "chat_messages" not in existing_tables:
            conn.execute(text("ALTER TABLE bcm_chat_messages RENAME TO chat_messages"))
            conn.execute(
                text("ALTER TABLE chat_messages ADD COLUMN scope VARCHAR NOT NULL DEFAULT 'bcm'")
            )
            # Old composite indexes carried the bcm_ prefix; drop them so the
            # new model's indexes (created by create_all below) don't sit
            # alongside redundant stale entries.
            conn.execute(text("DROP INDEX IF EXISTS ix_bcm_chat_project_created"))
            conn.execute(text("DROP INDEX IF EXISTS ix_bcm_chat_thread_created"))


def _migrate_dataset_annotation_columns(engine: Engine) -> None:
    """Idempotent: add Part-5 annotation columns to data_quality_datasets if missing.

    create_all() will not add columns to existing tables, so dev DBs that
    were created before Part 5 need an explicit ALTER. Fresh DBs get the
    columns at create_all time and this is a no-op.
    """
    inspector = inspect(engine)
    if "data_quality_datasets" not in inspector.get_table_names():
        return
    existing_cols = {c["name"] for c in inspector.get_columns("data_quality_datasets")}
    with engine.begin() as conn:
        if "annotation_status" not in existing_cols:
            conn.execute(
                text(
                    "ALTER TABLE data_quality_datasets "
                    "ADD COLUMN annotation_status VARCHAR NOT NULL DEFAULT 'pending'"
                )
            )
        if "annotation_error" not in existing_cols:
            conn.execute(
                text("ALTER TABLE data_quality_datasets ADD COLUMN annotation_error TEXT")
            )
        if "annotated_at" not in existing_cols:
            conn.execute(
                text("ALTER TABLE data_quality_datasets ADD COLUMN annotated_at DATETIME")
            )


def _migrate_dataset_config_column(engine: Engine) -> None:
    """Idempotent: add Epic 3 `config_completed_at` to data_quality_datasets.

    create_all() will not add new columns to an existing table, so dev DBs
    that pre-date Epic 3 need an explicit ALTER. Fresh DBs get the column
    at create_all time and this is a no-op."""
    inspector = inspect(engine)
    if "data_quality_datasets" not in inspector.get_table_names():
        return
    existing_cols = {c["name"] for c in inspector.get_columns("data_quality_datasets")}
    if "config_completed_at" not in existing_cols:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "ALTER TABLE data_quality_datasets "
                    "ADD COLUMN config_completed_at DATETIME"
                )
            )


def init_db(engine: Engine) -> None:
    """Create tables if missing and seed the project_types catalog. Idempotent."""
    # Late import to avoid a circular dep: models imports Base from this module.
    from app.models import ChatMessage, ChatThread, ProjectType

    _migrate_chat_tables(engine)
    _migrate_dataset_annotation_columns(engine)
    _migrate_dataset_config_column(engine)
    Base.metadata.create_all(engine)

    factory = sessionmaker(bind=engine)
    with factory() as db:
        existing_rows = {pt.code: pt for pt in db.query(ProjectType).all()}
        for seed in PROJECT_TYPE_SEED:
            row = existing_rows.get(seed["code"])
            if row is None:
                db.add(ProjectType(**seed))
            else:
                # Keep `is_active` in sync with the seed so flipping the flag
                # in code propagates to existing dev databases without manual
                # SQL. Name is also synced in case we ever rename a type.
                if row.is_active != seed["is_active"] or row.name != seed["name"]:
                    row.is_active = seed["is_active"]
                    row.name = seed["name"]
        db.commit()

        # Migrate any pre-thread chat messages onto a default thread per project.
        orphan_project_ids = {
            row[0]
            for row in db.query(ChatMessage.project_id)
            .filter(ChatMessage.thread_id.is_(None))
            .distinct()
            .all()
        }
        for pid in orphan_project_ids:
            thread = (
                db.query(ChatThread)
                .filter_by(project_id=pid, scope="bcm")
                .order_by(ChatThread.created_at.asc(), ChatThread.id.asc())
                .first()
            )
            if thread is None:
                thread = ChatThread(project_id=pid, scope="bcm", title="Default chat")
                db.add(thread)
                db.flush()
            db.query(ChatMessage).filter(
                ChatMessage.project_id == pid,
                ChatMessage.thread_id.is_(None),
            ).update(
                {"thread_id": thread.id, "scope": "bcm"}, synchronize_session=False
            )
        if orphan_project_ids:
            db.commit()
