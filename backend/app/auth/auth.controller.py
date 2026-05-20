"""Auth controller — HTTP-layer adapter between router and service.

Catches ValueError from the service and raises HTTPException.
Responsible for setting/deleting the session cookie on the response.
"""
from __future__ import annotations

from fastapi import HTTPException, Response, status

from app.common.security import SESSION_COOKIE
from app.auth.auth_service import handle_login, handle_logout


def login(username: str, password: str, response: Response) -> str:
    """Validate credentials, set the session cookie, return the username.

    Raises HTTPException 401 on invalid credentials.
    """
    try:
        session_id, username_out = handle_login(username, password)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc
    response.set_cookie(
        key=SESSION_COOKIE,
        value=session_id,
        httponly=True,
        samesite="lax",
        secure=False,
        path="/",
    )
    return username_out


def logout(session_id: str | None, response: Response) -> None:
    """Remove the session and delete the cookie."""
    handle_logout(session_id)
    response.delete_cookie(SESSION_COOKIE, path="/")
