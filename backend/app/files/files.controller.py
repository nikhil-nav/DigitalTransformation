"""Files controller — HTTP-layer adapter between router and service.

Catches ValueError from the service and raises HTTPException.
"""
from __future__ import annotations

from fastapi import HTTPException, status

from app.files.files_service import validate_file, require_anthropic_keys
from app.llm.session import session_keys


def get_keys_or_400(session_id: str | None):
    try:
        return require_anthropic_keys(session_id, session_keys)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def validate_upload_or_400(filename: str | None, contents: bytes, mime_type: str) -> str:
    """Return the file kind or raise HTTPException."""
    try:
        return validate_file(filename, contents, mime_type)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
