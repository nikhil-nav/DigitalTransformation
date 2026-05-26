import os
from collections.abc import Generator
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine

load_dotenv(Path(__file__).parent.parent.parent / ".env")
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL environment variable is required")
    return url


def make_engine(url: str | None = None) -> Engine:
    return create_engine(
        url if url is not None else database_url(),
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


def init_db(engine: Engine) -> None:
    """Run Alembic migrations to head and seed the project_types catalog. Idempotent."""
    # Late imports: avoid circular deps (models import Base from this module) and
    # avoid startup failures in test environments where alembic.ini may not exist.
    import alembic.command
    import alembic.config

    from app.models import ChatMessage, ChatThread, ProjectType

    alembic_ini = Path(__file__).parent.parent.parent / "alembic.ini"
    alembic_cfg = alembic.config.Config(str(alembic_ini))
    alembic_cfg.set_main_option("sqlalchemy.url", str(engine.url))
    alembic.command.upgrade(alembic_cfg, "head")

    factory = sessionmaker(bind=engine)
    with factory() as db:
        existing_rows = {pt.code: pt for pt in db.query(ProjectType).all()}
        for seed in PROJECT_TYPE_SEED:
            row = existing_rows.get(seed["code"])
            if row is None:
                db.add(ProjectType(**seed))
            else:
                if row.is_active != seed["is_active"] or row.name != seed["name"]:
                    row.is_active = seed["is_active"]
                    row.name = seed["name"]
        db.commit()

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
