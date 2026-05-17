"""File upload endpoints (PDFs and images) backed by the Anthropic Files API.

Files are uploaded to Anthropic and tracked in `bcm_files`. The agent loop
references them by Anthropic file id; we never store the bytes locally.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated

import anthropic
from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    File,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

from app.auth import SESSION_COOKIE, get_current_user_row
from app.bcm import _user_value_discovery_project_or_404
from app.db import get_db
from app.llm.session import LlmKeys, session_keys
from app.models import BcmFile, User
from app.schemas import FileOut

router = APIRouter(tags=["files"])

MAX_FILE_BYTES = 32 * 1024 * 1024  # 32 MB ceiling per file
ALLOWED_PDF_MIME = {"application/pdf"}
ALLOWED_IMAGE_MIME = {
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
}


def _require_anthropic_keys(session_id: str | None) -> LlmKeys:
    """Files are uploaded against the user's Anthropic key.

    The Anthropic Files API is not available for OpenAI; if the user
    selected OpenAI, we reject the upload with a clear error.
    """
    if session_id is None or session_id not in session_keys:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="LLM API key not configured. Set it in Chat Settings.",
        )
    keys = session_keys[session_id]
    if keys.provider != "anthropic":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "File uploads require the Anthropic provider. "
                "Switch to Claude in Chat Settings."
            ),
        )
    return keys


def _classify(mime_type: str) -> str:
    if mime_type in ALLOWED_PDF_MIME:
        return "pdf"
    if mime_type in ALLOWED_IMAGE_MIME:
        return "image"
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Unsupported file type: {mime_type}",
    )


@router.get(
    "/api/projects/{project_id}/files", response_model=list[FileOut]
)
def list_files(
    project_id: int,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> Sequence[BcmFile]:
    project = _user_value_discovery_project_or_404(db, project_id, user)
    return (
        db.query(BcmFile)
        .filter_by(project_id=project.id)
        .order_by(BcmFile.uploaded_at.desc())
        .all()
    )


@router.post(
    "/api/projects/{project_id}/files",
    response_model=FileOut,
    status_code=status.HTTP_201_CREATED,
)
def upload_file(
    project_id: int,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
    upload: Annotated[UploadFile, File()],
    session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> BcmFile:
    project = _user_value_discovery_project_or_404(db, project_id, user)
    keys = _require_anthropic_keys(session_id)

    if not upload.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload missing filename",
        )

    mime = upload.content_type or "application/octet-stream"
    kind = _classify(mime)

    contents = upload.file.read()
    size = len(contents)
    if size == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file"
        )
    if size > MAX_FILE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"File too large: {size} bytes (max {MAX_FILE_BYTES} bytes)"
            ),
        )

    client = anthropic.Anthropic(api_key=keys.llm_api_key)
    try:
        uploaded = client.beta.files.upload(
            file=(upload.filename, contents, mime),
        )
    except Exception as e:  # noqa: BLE001 - surface cleanly
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Anthropic Files upload failed: {e}",
        ) from e

    row = BcmFile(
        project_id=project.id,
        anthropic_file_id=uploaded.id,
        original_filename=upload.filename,
        kind=kind,
        mime_type=mime,
        size_bytes=size,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.delete(
    "/api/projects/{project_id}/files/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_file(
    project_id: int,
    file_id: int,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
    session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> None:
    project = _user_value_discovery_project_or_404(db, project_id, user)
    keys = _require_anthropic_keys(session_id)

    row = (
        db.query(BcmFile)
        .filter_by(id=file_id, project_id=project.id)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="File not found"
        )

    # Best-effort delete from Anthropic; ignore failures so we don't leave
    # the user stuck with stale rows when their key was revoked.
    try:
        client = anthropic.Anthropic(api_key=keys.llm_api_key)
        client.beta.files.delete(row.anthropic_file_id)
    except Exception:
        pass

    db.delete(row)
    db.commit()
