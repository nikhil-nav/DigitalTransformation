"""Chat thread CRUD endpoints — thin HTTP layer. Calls controller functions."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.auth import get_current_user_row
from app.common.db import get_db
from app.schemas import ChatThreadCreate, ChatThreadOut, ChatThreadUpdate

import app.threads.threads_repository as repo
from app.threads.threads_controller import (
    require_value_discovery_project,
    get_thread_or_404,
    get_or_create_default_thread,
)

router = APIRouter(tags=["threads"])


def ensure_default_thread(db: Session, project) -> object:
    """Return the project's oldest BCM thread, creating one if none exists.

    Public helper used by app.bcm.bcm.router and accessible via app.threads.
    """
    return get_or_create_default_thread(db, project)


@router.get(
    "/api/projects/{project_id}/threads", response_model=list[ChatThreadOut]
)
def list_threads(
    project_id: int,
    user: Annotated[object, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> Sequence:
    project = require_value_discovery_project(db, project_id, user)
    ensure_default_thread(db, project)
    return repo.list_threads(db, project.id, "bcm")


@router.post(
    "/api/projects/{project_id}/threads",
    response_model=ChatThreadOut,
    status_code=status.HTTP_201_CREATED,
)
def create_thread(
    project_id: int,
    body: ChatThreadCreate,
    user: Annotated[object, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
):
    project = require_value_discovery_project(db, project_id, user)
    title = (body.title and body.title.strip()) or "New chat"
    return repo.create_thread(db, project.id, "bcm", title)


@router.patch(
    "/api/projects/{project_id}/threads/{thread_id}",
    response_model=ChatThreadOut,
)
def rename_thread(
    project_id: int,
    thread_id: int,
    body: ChatThreadUpdate,
    user: Annotated[object, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
):
    require_value_discovery_project(db, project_id, user)
    thread = get_thread_or_404(db, thread_id, project_id)
    return repo.update_thread_title(db, thread, body.title.strip())


@router.delete(
    "/api/projects/{project_id}/threads/{thread_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_thread(
    project_id: int,
    thread_id: int,
    user: Annotated[object, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    require_value_discovery_project(db, project_id, user)
    thread = get_thread_or_404(db, thread_id, project_id)
    repo.delete_thread(db, thread)
