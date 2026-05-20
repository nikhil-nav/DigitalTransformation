"""Auth router — thin HTTP layer. Session cookie management and LLM key endpoints."""
from typing import Annotated, Literal

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.common.db import get_db
from app.common.security import SESSION_COOKIE, sessions
from app.llm.session import (
    ALLOWED_MODELS_BY_PROVIDER,
    LlmKeys,
    LlmProvider,
    session_keys,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    username: str


class LlmKeysRequest(BaseModel):
    provider: Literal["anthropic", "openai"]
    llm_api_key: str = Field(min_length=10)
    model: str | None = None


class LlmKeysStatus(BaseModel):
    provider: LlmProvider | None = None
    llm_configured: bool
    model: str | None = None
    available_models: list[str] = Field(default_factory=list)


def get_current_user(
    session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> str:
    if session_id is None or session_id not in sessions:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return sessions[session_id]


def get_current_user_row(
    username: Annotated[str, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Resolve the authenticated session to a User row, creating it on first use."""
    from app.models import User

    user = db.query(User).filter_by(username=username).one_or_none()
    if user is None:
        user = User(username=username)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def _status_for(keys: LlmKeys | None) -> LlmKeysStatus:
    if keys is None:
        return LlmKeysStatus(provider=None, llm_configured=False, model=None, available_models=[])
    return LlmKeysStatus(
        provider=keys.provider,
        llm_configured=True,
        model=keys.model,
        available_models=list(ALLOWED_MODELS_BY_PROVIDER[keys.provider]),
    )


@router.post("/login")
def login(body: LoginRequest, response: Response) -> UserResponse:
    from app.auth.auth_controller import login as ctrl_login
    username = ctrl_login(body.username, body.password, response)
    return UserResponse(username=username)


@router.post("/logout")
def logout(
    response: Response,
    session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> dict[str, str]:
    from app.auth.auth_controller import logout as ctrl_logout
    ctrl_logout(session_id, response)
    return {"status": "ok"}


@router.get("/llm-keys", response_model=LlmKeysStatus)
def get_llm_keys_status(
    _username: Annotated[str, Depends(get_current_user)],
    session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> LlmKeysStatus:
    keys = session_keys.get(session_id) if session_id else None
    return _status_for(keys)


@router.post("/llm-keys", response_model=LlmKeysStatus)
def set_llm_keys(
    body: LlmKeysRequest,
    _username: Annotated[str, Depends(get_current_user)],
    session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> LlmKeysStatus:
    if session_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="No session"
        )
    if body.model is not None and body.model not in ALLOWED_MODELS_BY_PROVIDER[body.provider]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Model '{body.model}' is not available for provider "
                f"'{body.provider}'. Allowed: "
                f"{', '.join(ALLOWED_MODELS_BY_PROVIDER[body.provider])}"
            ),
        )
    keys = LlmKeys(
        provider=body.provider,
        llm_api_key=body.llm_api_key,
        model=body.model,
    )
    session_keys[session_id] = keys
    return _status_for(keys)


@router.delete("/llm-keys", response_model=LlmKeysStatus)
def clear_llm_keys(
    _username: Annotated[str, Depends(get_current_user)],
    session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> LlmKeysStatus:
    if session_id is not None:
        session_keys.pop(session_id, None)
    return _status_for(None)


@router.get("/me")
def me(username: Annotated[str, Depends(get_current_user)]) -> UserResponse:
    return UserResponse(username=username)
