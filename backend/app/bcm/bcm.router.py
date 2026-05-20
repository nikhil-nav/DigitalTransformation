"""BCM router — thin HTTP layer. Calls controller functions."""
import json
from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.auth import SESSION_COOKIE, get_current_user_row
from app.common.db import get_db
from app.llm.session import LlmKeys, session_keys
from app.schemas import (
    CapabilityCreate,
    CapabilityOut,
    CapabilityUpdate,
    ChatMessageCreate,
    ChatMessageOut,
)

import app.bcm.bcm_repository as repo
from app.bcm.bcm_controller import (
    require_value_discovery_project,
    check_hierarchy,
    get_capability_or_404,
    resolve_files_or_400,
    resolve_thread,
)

BCM_SCOPE = "bcm"

router = APIRouter(tags=["bcm"])


def _require_llm_keys(session_id: str | None) -> LlmKeys:
    if session_id is None or session_id not in session_keys:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="LLM API key not configured. Set it in Chat Settings.",
        )
    return session_keys[session_id]


# --- Capabilities ---

@router.get(
    "/api/projects/{project_id}/capabilities", response_model=list[CapabilityOut]
)
def list_capabilities(
    project_id: int,
    user: Annotated[object, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> Sequence:
    project = require_value_discovery_project(db, project_id, user)
    return repo.list_capabilities(db, project.id)


@router.post(
    "/api/projects/{project_id}/capabilities",
    response_model=CapabilityOut,
    status_code=status.HTTP_201_CREATED,
)
def create_capability(
    project_id: int,
    body: CapabilityCreate,
    user: Annotated[object, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
):
    project = require_value_discovery_project(db, project_id, user)
    check_hierarchy(db, project, body.level, body.parent_id)
    position = (
        body.position
        if body.position is not None
        else repo.get_last_sibling_position(db, project.id, body.parent_id)
    )
    return repo.create_capability(
        db, project.id, body.parent_id, body.level,
        body.name, body.description, position
    )


@router.patch(
    "/api/projects/{project_id}/capabilities/{cap_id}", response_model=CapabilityOut
)
def update_capability(
    project_id: int,
    cap_id: int,
    body: CapabilityUpdate,
    user: Annotated[object, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
):
    project = require_value_discovery_project(db, project_id, user)
    cap = get_capability_or_404(db, cap_id, project.id)
    data = body.model_dump(exclude_unset=True)
    if "parent_id" in data:
        check_hierarchy(db, project, cap.level, data["parent_id"])
    return repo.update_capability(db, cap, **data)


@router.delete(
    "/api/projects/{project_id}/capabilities/{cap_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_capability(
    project_id: int,
    cap_id: int,
    user: Annotated[object, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    project = require_value_discovery_project(db, project_id, user)
    cap = get_capability_or_404(db, cap_id, project.id)
    repo.delete_capability(db, cap)


# --- Chat ---

@router.get(
    "/api/projects/{project_id}/chat", response_model=list[ChatMessageOut]
)
def list_chat(
    project_id: int,
    user: Annotated[object, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
    thread_id: int | None = None,
) -> Sequence:
    project = require_value_discovery_project(db, project_id, user)
    thread = resolve_thread(db, project, thread_id)
    return repo.get_chat_messages(db, project.id, thread.id, BCM_SCOPE)


@router.post(
    "/api/projects/{project_id}/chat",
    response_model=list[ChatMessageOut],
    status_code=status.HTTP_201_CREATED,
)
def post_chat(
    project_id: int,
    body: ChatMessageCreate,
    user: Annotated[object, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
    session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> list:
    from app.llm.agent import run_agent_turn
    project = require_value_discovery_project(db, project_id, user)
    keys = _require_llm_keys(session_id)
    thread = resolve_thread(db, project, body.thread_id)
    attachment_file_ids = resolve_files_or_400(db, project, body.file_ids)
    result = run_agent_turn(
        db=db,
        project_id=project.id,
        thread_id=thread.id,
        user_message=body.content,
        keys=keys,
        attachment_file_ids=attachment_file_ids,
    )
    return [result.user_message, result.assistant_message]


def _format_sse(event_type: str, data: dict | None = None) -> str:
    payload = json.dumps(data or {}, default=str)
    return f"event: {event_type}\ndata: {payload}\n\n"


@router.post("/api/projects/{project_id}/chat/stream")
def post_chat_stream(
    project_id: int,
    body: ChatMessageCreate,
    user: Annotated[object, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
    session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> StreamingResponse:
    from app.llm.agent import run_agent_turn_stream
    project = require_value_discovery_project(db, project_id, user)
    keys = _require_llm_keys(session_id)
    thread = resolve_thread(db, project, body.thread_id)
    attachment_file_ids = resolve_files_or_400(db, project, body.file_ids)

    def event_stream():
        try:
            for event in run_agent_turn_stream(
                db=db,
                project_id=project.id,
                thread_id=thread.id,
                user_message=body.content,
                keys=keys,
                attachment_file_ids=attachment_file_ids,
            ):
                yield _format_sse(event["type"], event.get("data") or {})
            yield _format_sse("done")
        except Exception as e:  # noqa: BLE001 - surface as SSE error
            yield _format_sse("error", {"message": str(e)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# Public helper used by files.router — must remain accessible via app.bcm
def _user_value_discovery_project_or_404(db: Session, project_id: int, user):
    """Backward-compat shim for files.router which calls this directly."""
    return require_value_discovery_project(db, project_id, user)
