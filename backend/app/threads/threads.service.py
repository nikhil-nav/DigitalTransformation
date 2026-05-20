"""Threads service — business logic. No FastAPI imports allowed (AC-6)."""
from __future__ import annotations

from sqlalchemy.orm import Session

VALUE_DISCOVERY_CODE = "value_discovery"
BCM_SCOPE = "bcm"


def get_value_discovery_project_or_raise(db: Session, project_id: int, user_id: int):
    """Return a Value Discovery project or raise ValueError."""
    from app.models import Project
    project = db.query(Project).filter_by(id=project_id, user_id=user_id).one_or_none()
    if project is None:
        raise ValueError("Project not found")
    if project.project_type.code != VALUE_DISCOVERY_CODE:
        raise ValueError(
            f"BCM is only available for Value Discovery projects "
            f"(this project is '{project.project_type.code}')"
        )
    return project


def get_thread_or_raise(db: Session, thread_id: int, project_id: int, scope: str):
    """Return a thread or raise ValueError."""
    from app.threads.threads_repository import get_thread
    thread = get_thread(db, thread_id, project_id, scope)
    if thread is None:
        raise ValueError("Chat thread not found")
    return thread


def ensure_default_thread(db: Session, project):
    """Return or create the default BCM thread for a project."""
    from app.threads.threads_repository import get_oldest_thread, create_thread
    thread = get_oldest_thread(db, project.id, BCM_SCOPE)
    if thread is not None:
        return thread
    return create_thread(db, project.id, BCM_SCOPE, "New chat")
