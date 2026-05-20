"""Projects controller — HTTP-layer adapter between router and service.

Catches ValueError from the service and raises HTTPException.
"""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.projects.projects_service import (
    get_active_project_type,
    get_user_project_or_raise,
    get_project_opportunity_or_raise,
)


def require_active_project_type(db: Session, code: str):
    try:
        return get_active_project_type(db, code)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def require_user_project(db: Session, project_id: int, user):
    try:
        return get_user_project_or_raise(db, project_id, user.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def require_project_opportunity(db: Session, project_id: int, opportunity_id: int):
    try:
        return get_project_opportunity_or_raise(db, project_id, opportunity_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
