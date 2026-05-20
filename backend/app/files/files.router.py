"""File upload endpoints — thin HTTP layer. Calls controller functions."""
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
from app.common.db import get_db
from app.schemas import FileOut

import app.files.files_repository as repo
from app.files.files_controller import get_keys_or_400, validate_upload_or_400

router = APIRouter(tags=["files"])


@router.get(
    "/api/projects/{project_id}/files", response_model=list[FileOut]
)
def list_files(
    project_id: int,
    user: Annotated[object, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> Sequence:
    from app.bcm import _user_value_discovery_project_or_404
    project = _user_value_discovery_project_or_404(db, project_id, user)
    return repo.list_project_files(db, project.id)


@router.post(
    "/api/projects/{project_id}/files",
    response_model=FileOut,
    status_code=status.HTTP_201_CREATED,
)
def upload_file(
    project_id: int,
    user: Annotated[object, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
    upload: Annotated[UploadFile, File()],
    session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
):
    from app.bcm import _user_value_discovery_project_or_404
    project = _user_value_discovery_project_or_404(db, project_id, user)
    keys = get_keys_or_400(session_id)

    mime = upload.content_type or "application/octet-stream"
    contents = upload.file.read()
    kind = validate_upload_or_400(upload.filename, contents, mime)

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

    return repo.create_file(
        db,
        project_id=project.id,
        anthropic_file_id=uploaded.id,
        original_filename=upload.filename,
        kind=kind,
        mime_type=mime,
        size_bytes=len(contents),
    )


@router.delete(
    "/api/projects/{project_id}/files/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_file(
    project_id: int,
    file_id: int,
    user: Annotated[object, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
    session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> None:
    from app.bcm import _user_value_discovery_project_or_404
    project = _user_value_discovery_project_or_404(db, project_id, user)
    keys = get_keys_or_400(session_id)

    row = repo.get_file(db, file_id, project.id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="File not found"
        )

    try:
        client = anthropic.Anthropic(api_key=keys.llm_api_key)
        client.beta.files.delete(row.anthropic_file_id)
    except Exception:
        pass

    repo.delete_file(db, row)
