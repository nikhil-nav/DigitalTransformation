"""BCM controller — HTTP-layer adapter between router and service.

Catches ValueError from the service and raises HTTPException.
"""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.bcm.bcm_service import (
    get_value_discovery_project_or_raise,
    validate_hierarchy,
    resolve_attachment_file_ids,
)
from app.bcm import bcm_repository as repo

BCM_SCOPE = "bcm"


def require_value_discovery_project(db: Session, project_id: int, user):
    try:
        return get_value_discovery_project_or_raise(db, project_id, user.id)
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)


def check_hierarchy(db: Session, project, level: int, parent_id: int | None) -> None:
    try:
        validate_hierarchy(db, project, level, parent_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def get_capability_or_404(db: Session, cap_id: int, project_id: int):
    cap = repo.get_capability(db, cap_id, project_id)
    if cap is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Capability not found")
    return cap


def resolve_files_or_400(db: Session, project, ids: list[int] | None) -> list[str]:
    try:
        return resolve_attachment_file_ids(db, project, ids)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def resolve_thread(db: Session, project, thread_id: int | None):
    if thread_id is not None:
        thread = repo.get_chat_thread(db, thread_id, project.id, BCM_SCOPE)
        if thread is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Thread does not belong to this project",
            )
        return thread
    from app.threads import ensure_default_thread
    return ensure_default_thread(db, project)
