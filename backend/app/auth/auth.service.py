"""Auth service — no FastAPI imports allowed here (AC-6).

Business logic only. Raises ValueError for domain errors.
FastAPI-specific dependencies (HTTPException, Cookie, Depends) live in auth.router.py.
"""
import secrets

from app.common.security import SESSION_COOKIE, sessions
from app.llm.session import (
    ALLOWED_MODELS_BY_PROVIDER,
    LlmKeys,
    session_keys,
)

# Hardcoded credentials for the MVP per agents.md.
HARDCODED_USERNAME = "user"
HARDCODED_PASSWORD = "password"


def handle_login(username: str, password: str) -> tuple[str, str]:
    """Validate credentials and return (session_id, username).

    Raises ValueError on invalid credentials.
    """
    if username != HARDCODED_USERNAME or password != HARDCODED_PASSWORD:
        raise ValueError("Invalid credentials")
    session_id = secrets.token_urlsafe(32)
    sessions[session_id] = username
    return session_id, username


def handle_logout(session_id: str | None) -> None:
    if session_id is not None:
        sessions.pop(session_id, None)
        session_keys.pop(session_id, None)


def handle_set_llm_keys(session_id: str | None, provider: str, llm_api_key: str, model: str | None):
    if session_id is None:
        raise ValueError("No session")
    if model is not None and model not in ALLOWED_MODELS_BY_PROVIDER[provider]:
        raise ValueError(
            f"Model '{model}' is not available for provider "
            f"'{provider}'. Allowed: "
            f"{', '.join(ALLOWED_MODELS_BY_PROVIDER[provider])}"
        )
    keys = LlmKeys(
        provider=provider,
        llm_api_key=llm_api_key,
        model=model,
    )
    session_keys[session_id] = keys
    return _status_for(keys)


def handle_get_llm_keys(session_id: str | None):
    keys = session_keys.get(session_id) if session_id else None
    return _status_for(keys)


def handle_clear_llm_keys(session_id: str | None):
    if session_id is not None:
        session_keys.pop(session_id, None)
    return _status_for(None)


def _status_for(keys: LlmKeys | None) -> dict:
    """Return a plain dict representation of LLM key status.

    The router layer is responsible for converting this to a Pydantic response model.
    """
    if keys is None:
        return {"provider": None, "llm_configured": False, "model": None, "available_models": []}
    return {
        "provider": keys.provider,
        "llm_configured": True,
        "model": keys.model,
        "available_models": list(ALLOWED_MODELS_BY_PROVIDER[keys.provider]),
    }
