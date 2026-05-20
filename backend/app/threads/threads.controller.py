"""Threads controller — HTTP-layer adapter between router and service.

Catches ValueError from the service and raises HTTPException.
"""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.threads.threads_service import (
    get_value_discovery_project_or_raise,
    get_thread_or_raise,
    ensure_default_thread,
)

BCM_SCOPE = "bcm"


def require_value_discovery_project(db: Session, project_id: int, user):
    try:
        return get_value_discovery_project_or_raise(db, project_id, user.id)
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)


def get_thread_or_404(db: Session, thread_id: int, project_id: int):
    try:
        return get_thread_or_raise(db, thread_id, project_id, BCM_SCOPE)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def get_or_create_default_thread(db: Session, project):
    return ensure_default_thread(db, project)
