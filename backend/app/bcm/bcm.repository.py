"""BCM repository — SQLAlchemy queries only. No FastAPI imports allowed."""
from __future__ import annotations

from sqlalchemy.orm import Session


def get_project(db: Session, project_id: int, user_id: int):
    """Return a Project row or None."""
    from app.models import Project
    return db.query(Project).filter_by(id=project_id, user_id=user_id).one_or_none()


def list_capabilities(db: Session, project_id: int):
    """Return all capabilities for a project ordered by level then position."""
    from app.models import BcmCapability
    return (
        db.query(BcmCapability)
        .filter_by(project_id=project_id)
        .order_by(BcmCapability.level.asc(), BcmCapability.position.asc())
        .all()
    )


def get_capability(db: Session, cap_id: int, project_id: int):
    """Return a single capability or None."""
    from app.models import BcmCapability
    return db.query(BcmCapability).filter_by(id=cap_id, project_id=project_id).one_or_none()


def get_parent_capability(db: Session, parent_id: int, project_id: int):
    """Return parent capability or None."""
    from app.models import BcmCapability
    return db.query(BcmCapability).filter_by(id=parent_id, project_id=project_id).one_or_none()


def get_last_sibling_position(db: Session, project_id: int, parent_id: int | None) -> int:
    """Return the next available position under a parent."""
    from app.models import BcmCapability
    last = (
        db.query(BcmCapability)
        .filter_by(project_id=project_id, parent_id=parent_id)
        .order_by(BcmCapability.position.desc())
        .first()
    )
    return (last.position + 1) if last else 0


def create_capability(db: Session, project_id: int, parent_id: int | None,
                      level: int, name: str, description: str | None, position: int):
    """Insert and return a new BcmCapability row."""
    from app.models import BcmCapability
    cap = BcmCapability(
        project_id=project_id,
        parent_id=parent_id,
        level=level,
        name=name,
        description=description,
        position=position,
    )
    db.add(cap)
    db.commit()
    db.refresh(cap)
    return cap


def update_capability(db: Session, cap, **updates):
    """Apply field updates to a capability and commit."""
    for key, value in updates.items():
        setattr(cap, key, value)
    db.commit()
    db.refresh(cap)
    return cap


def delete_capability(db: Session, cap) -> None:
    """Delete a capability row."""
    db.delete(cap)
    db.commit()


def get_bcm_file(db: Session, file_id: int, project_id: int):
    """Return a BcmFile row or None."""
    from app.models import BcmFile
    return db.query(BcmFile).filter_by(id=file_id, project_id=project_id).one_or_none()


def get_bcm_files_by_ids(db: Session, project_id: int, ids: list[int]):
    """Return BcmFile rows matching the given ids within the project."""
    from app.models import BcmFile
    return (
        db.query(BcmFile)
        .filter(BcmFile.project_id == project_id, BcmFile.id.in_(ids))
        .all()
    )


def get_chat_messages(db: Session, project_id: int, thread_id: int, scope: str):
    """Return chat messages for a project+thread+scope ordered by time."""
    from app.models import ChatMessage
    return (
        db.query(ChatMessage)
        .filter_by(project_id=project_id, thread_id=thread_id, scope=scope)
        .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
        .all()
    )


def get_chat_thread(db: Session, thread_id: int, project_id: int, scope: str):
    """Return a specific chat thread or None."""
    from app.models import ChatThread
    return (
        db.query(ChatThread)
        .filter_by(id=thread_id, project_id=project_id, scope=scope)
        .one_or_none()
    )
