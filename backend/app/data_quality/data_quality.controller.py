"""Data Quality controller — HTTP-layer adapter between router and service.

Catches ValueError from the service and raises HTTPException.
"""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.data_quality.data_quality_service import (
    get_data_quality_project_or_raise,
    get_dataset_or_raise,
    require_llm_keys,
)


def require_dq_project(db: Session, project_id: int, user):
    try:
        return get_data_quality_project_or_raise(db, project_id, user.id)
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)


def require_dataset(db: Session, project, dataset_id: int):
    try:
        return get_dataset_or_raise(db, project, dataset_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def get_llm_keys_or_400(session_id: str | None, session_keys: dict):
    try:
        return require_llm_keys(session_id, session_keys)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
