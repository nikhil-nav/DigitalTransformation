"""Chat thread CRUD endpoints, scoped to a Value Discovery project."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import get_current_user_row
from app.db import get_db
from app.models import ChatThread, Project, User
from app.schemas import ChatThreadCreate, ChatThreadOut, ChatThreadUpdate

router = APIRouter(tags=["threads"])

VALUE_DISCOVERY_CODE = "value_discovery"
BCM_SCOPE = "bcm"


def _user_value_discovery_project_or_404(
    db: Session, project_id: int, user: User
) -> Project:
    project = (
        db.query(Project).filter_by(id=project_id, user_id=user.id).one_or_none()
    )
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        )
    if project.project_type.code != VALUE_DISCOVERY_CODE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"BCM is only available for Value Discovery projects "
                f"(this project is '{project.project_type.code}')"
            ),
        )
    return project


def _project_thread_or_404(
    db: Session, project: Project, thread_id: int
) -> ChatThread:
    thread = (
        db.query(ChatThread)
        .filter_by(id=thread_id, project_id=project.id, scope=BCM_SCOPE)
        .one_or_none()
    )
    if thread is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat thread not found",
        )
    return thread


def ensure_default_thread(db: Session, project: Project) -> ChatThread:
    """Return the project's oldest BCM thread, creating one if none exists."""
    thread = (
        db.query(ChatThread)
        .filter_by(project_id=project.id, scope=BCM_SCOPE)
        .order_by(ChatThread.created_at.asc(), ChatThread.id.asc())
        .first()
    )
    if thread is not None:
        return thread
    thread = ChatThread(project_id=project.id, scope=BCM_SCOPE, title="New chat")
    db.add(thread)
    db.commit()
    db.refresh(thread)
    return thread


@router.get(
    "/api/projects/{project_id}/threads", response_model=list[ChatThreadOut]
)
def list_threads(
    project_id: int,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> Sequence[ChatThread]:
    project = _user_value_discovery_project_or_404(db, project_id, user)
    # Lazily create a default thread the first time the UI asks; means the
    # thread sidebar always has at least one entry.
    ensure_default_thread(db, project)
    return (
        db.query(ChatThread)
        .filter_by(project_id=project.id, scope=BCM_SCOPE)
        .order_by(ChatThread.created_at.asc(), ChatThread.id.asc())
        .all()
    )


@router.post(
    "/api/projects/{project_id}/threads",
    response_model=ChatThreadOut,
    status_code=status.HTTP_201_CREATED,
)
def create_thread(
    project_id: int,
    body: ChatThreadCreate,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> ChatThread:
    project = _user_value_discovery_project_or_404(db, project_id, user)
    thread = ChatThread(
        project_id=project.id,
        scope=BCM_SCOPE,
        title=(body.title and body.title.strip()) or "New chat",
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)
    return thread


@router.patch(
    "/api/projects/{project_id}/threads/{thread_id}",
    response_model=ChatThreadOut,
)
def rename_thread(
    project_id: int,
    thread_id: int,
    body: ChatThreadUpdate,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> ChatThread:
    project = _user_value_discovery_project_or_404(db, project_id, user)
    thread = _project_thread_or_404(db, project, thread_id)
    thread.title = body.title.strip()
    db.commit()
    db.refresh(thread)
    return thread


@router.delete(
    "/api/projects/{project_id}/threads/{thread_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_thread(
    project_id: int,
    thread_id: int,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    project = _user_value_discovery_project_or_404(db, project_id, user)
    thread = _project_thread_or_404(db, project, thread_id)
    db.delete(thread)
    db.commit()
