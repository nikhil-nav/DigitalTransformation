"""Threads repository — SQLAlchemy queries only. No FastAPI imports allowed."""
from __future__ import annotations

from sqlalchemy.orm import Session

BCM_SCOPE = "bcm"


def get_thread(db: Session, thread_id: int, project_id: int, scope: str):
    """Return a ChatThread or None."""
    from app.models import ChatThread
    return (
        db.query(ChatThread)
        .filter_by(id=thread_id, project_id=project_id, scope=scope)
        .one_or_none()
    )


def list_threads(db: Session, project_id: int, scope: str):
    """Return all threads for a project+scope ordered by creation time."""
    from app.models import ChatThread
    return (
        db.query(ChatThread)
        .filter_by(project_id=project_id, scope=scope)
        .order_by(ChatThread.created_at.asc(), ChatThread.id.asc())
        .all()
    )


def get_oldest_thread(db: Session, project_id: int, scope: str):
    """Return the oldest thread for a project+scope, or None."""
    from app.models import ChatThread
    return (
        db.query(ChatThread)
        .filter_by(project_id=project_id, scope=scope)
        .order_by(ChatThread.created_at.asc(), ChatThread.id.asc())
        .first()
    )


def create_thread(db: Session, project_id: int, scope: str, title: str):
    """Insert and return a new ChatThread."""
    from app.models import ChatThread
    thread = ChatThread(project_id=project_id, scope=scope, title=title)
    db.add(thread)
    db.commit()
    db.refresh(thread)
    return thread


def update_thread_title(db: Session, thread, title: str):
    """Update thread title and return updated row."""
    thread.title = title
    db.commit()
    db.refresh(thread)
    return thread


def delete_thread(db: Session, thread) -> None:
    """Delete a thread."""
    db.delete(thread)
    db.commit()
