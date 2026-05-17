import json
from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.auth import SESSION_COOKIE, get_current_user_row
from app.db import get_db
from app.llm.agent import run_agent_turn, run_agent_turn_stream
from app.llm.session import LlmKeys, session_keys
from app.models import (
    BcmCapability,
    BcmFile,
    ChatMessage,
    ChatThread,
    Project,
    User,
)

BCM_SCOPE = "bcm"
from app.schemas import (
    CapabilityCreate,
    CapabilityOut,
    CapabilityUpdate,
    ChatMessageCreate,
    ChatMessageOut,
)
from app.threads import ensure_default_thread

router = APIRouter(tags=["bcm"])

VALUE_DISCOVERY_CODE = "value_discovery"


def _require_llm_keys(session_id: str | None) -> LlmKeys:
    if session_id is None or session_id not in session_keys:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="LLM API key not configured. Set it in Chat Settings.",
        )
    return session_keys[session_id]


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


def _validate_hierarchy(
    db: Session, project: Project, level: int, parent_id: int | None
) -> None:
    if level == 1:
        if parent_id is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="L1 capabilities cannot have a parent",
            )
        return

    if parent_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"L{level} capabilities require a parent",
        )

    parent = (
        db.query(BcmCapability)
        .filter_by(id=parent_id, project_id=project.id)
        .one_or_none()
    )
    if parent is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Parent capability not found in this project",
        )

    expected = level - 1
    if parent.level != expected:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"L{level} parent must be L{expected}, got L{parent.level}",
        )


def _next_position(db: Session, project_id: int, parent_id: int | None) -> int:
    last = (
        db.query(BcmCapability)
        .filter_by(project_id=project_id, parent_id=parent_id)
        .order_by(BcmCapability.position.desc())
        .first()
    )
    return (last.position + 1) if last else 0


# --- Capabilities ---

@router.get(
    "/api/projects/{project_id}/capabilities", response_model=list[CapabilityOut]
)
def list_capabilities(
    project_id: int,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> Sequence[BcmCapability]:
    project = _user_value_discovery_project_or_404(db, project_id, user)
    return (
        db.query(BcmCapability)
        .filter_by(project_id=project.id)
        .order_by(BcmCapability.level.asc(), BcmCapability.position.asc())
        .all()
    )


@router.post(
    "/api/projects/{project_id}/capabilities",
    response_model=CapabilityOut,
    status_code=status.HTTP_201_CREATED,
)
def create_capability(
    project_id: int,
    body: CapabilityCreate,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> BcmCapability:
    project = _user_value_discovery_project_or_404(db, project_id, user)
    _validate_hierarchy(db, project, body.level, body.parent_id)

    position = (
        body.position
        if body.position is not None
        else _next_position(db, project.id, body.parent_id)
    )
    cap = BcmCapability(
        project_id=project.id,
        parent_id=body.parent_id,
        level=body.level,
        name=body.name,
        description=body.description,
        position=position,
    )
    db.add(cap)
    db.commit()
    db.refresh(cap)
    return cap


@router.patch(
    "/api/projects/{project_id}/capabilities/{cap_id}", response_model=CapabilityOut
)
def update_capability(
    project_id: int,
    cap_id: int,
    body: CapabilityUpdate,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> BcmCapability:
    project = _user_value_discovery_project_or_404(db, project_id, user)
    cap = (
        db.query(BcmCapability)
        .filter_by(id=cap_id, project_id=project.id)
        .one_or_none()
    )
    if cap is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Capability not found"
        )

    data = body.model_dump(exclude_unset=True)

    if "parent_id" in data:
        _validate_hierarchy(db, project, cap.level, data["parent_id"])

    for key, value in data.items():
        setattr(cap, key, value)

    db.commit()
    db.refresh(cap)
    return cap


@router.delete(
    "/api/projects/{project_id}/capabilities/{cap_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_capability(
    project_id: int,
    cap_id: int,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    project = _user_value_discovery_project_or_404(db, project_id, user)
    cap = (
        db.query(BcmCapability)
        .filter_by(id=cap_id, project_id=project.id)
        .one_or_none()
    )
    if cap is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Capability not found"
        )
    db.delete(cap)
    db.commit()


# --- Chat (stub; real LLM lands in Part C) ---

@router.get(
    "/api/projects/{project_id}/chat", response_model=list[ChatMessageOut]
)
def list_chat(
    project_id: int,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
    thread_id: int | None = None,
) -> Sequence[ChatMessage]:
    project = _user_value_discovery_project_or_404(db, project_id, user)
    thread = _resolve_thread(db, project, thread_id)
    return (
        db.query(ChatMessage)
        .filter_by(project_id=project.id, thread_id=thread.id, scope=BCM_SCOPE)
        .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
        .all()
    )


def _resolve_thread(
    db: Session, project: Project, thread_id: int | None
) -> ChatThread:
    if thread_id is not None:
        thread = (
            db.query(ChatThread)
            .filter_by(id=thread_id, project_id=project.id, scope=BCM_SCOPE)
            .one_or_none()
        )
        if thread is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Thread does not belong to this project",
            )
        return thread
    return ensure_default_thread(db, project)


def _resolve_attachment_file_ids(
    db: Session, project: Project, ids: list[int] | None
) -> list[str]:
    if not ids:
        return []
    rows = (
        db.query(BcmFile)
        .filter(BcmFile.project_id == project.id, BcmFile.id.in_(ids))
        .all()
    )
    found = {row.id: row for row in rows}
    missing = [i for i in ids if i not in found]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File ids not found in this project: {missing}",
        )
    return [found[i].anthropic_file_id for i in ids]


@router.post(
    "/api/projects/{project_id}/chat",
    response_model=list[ChatMessageOut],
    status_code=status.HTTP_201_CREATED,
)
def post_chat(
    project_id: int,
    body: ChatMessageCreate,
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
    session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> list[ChatMessage]:
    project = _user_value_discovery_project_or_404(db, project_id, user)
    keys = _require_llm_keys(session_id)
    thread = _resolve_thread(db, project, body.thread_id)
    attachment_file_ids = _resolve_attachment_file_ids(
        db, project, body.file_ids
    )
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
    user: Annotated[User, Depends(get_current_user_row)],
    db: Annotated[Session, Depends(get_db)],
    session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> StreamingResponse:
    project = _user_value_discovery_project_or_404(db, project_id, user)
    keys = _require_llm_keys(session_id)
    thread = _resolve_thread(db, project, body.thread_id)
    attachment_file_ids = _resolve_attachment_file_ids(
        db, project, body.file_ids
    )

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
