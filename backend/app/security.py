"""Session authentication.

A signed cookie is enough for a demo: no password ever leaves the server, the
token carries only the username, and it expires on its own.
"""
from __future__ import annotations

from fastapi import Cookie, Depends, HTTPException, Response, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import User

COOKIE_NAME = "ai_sales_session"
_serializer = URLSafeTimedSerializer(settings.secret_key, salt="ai-sales-demo")


def issue_session(response: Response, user: User) -> None:
    token = _serializer.dumps({"u": user.username, "r": user.role})
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        path="/",
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def _decode(token: str) -> dict | None:
    try:
        return _serializer.loads(token, max_age=settings.session_ttl_hours * 3600)
    except (BadSignature, SignatureExpired):
        return None


def current_user(
    session: str | None = Cookie(default=None, alias=COOKIE_NAME),
    db: Session = Depends(get_db),
) -> User | None:
    if not session:
        return None
    payload = _decode(session)
    if not payload:
        return None
    return db.execute(
        select(User).where(User.username == payload.get("u"))
    ).scalars().first()


def require_user(user: User | None = Depends(current_user)) -> User:
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Требуется вход в систему")
    return user
