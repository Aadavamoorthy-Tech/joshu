"""Reusable Bearer session token validation middleware and FastAPI dependencies."""

from __future__ import annotations

from typing import Optional

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session as DBSession

from app.database import get_db
from app.models.session import Session as UserSession
from app.models.session import utc_now


def auth_error(status_code: int, error: str, message: str) -> HTTPException:
    """Build a structured JSON HTTPException matching the API error contract."""
    return HTTPException(
        status_code=status_code,
        detail={
            "error": error,
            "message": message,
            "status": status_code,
        },
    )


def extract_bearer_token(authorization: Optional[str]) -> str:
    """Validate and extract the opaque token from an `Authorization: Bearer <token>` header."""
    if not authorization:
        raise auth_error(401, "missing_authorization", "Authorization header is required")

    parts = authorization.strip().split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise auth_error(
            401,
            "invalid_authorization_header",
            "Authorization header must use Bearer token format",
        )

    return parts[1].strip()


async def validate_session(authorization: Optional[str], db: DBSession) -> UserSession:
    """
    Validate an opaque Bearer session token against the database.

    Raises HTTPException(401) if the token is missing, malformed, inactive,
    unknown, or expired.
    """
    token = extract_bearer_token(authorization)

    session_record = (
        db.query(UserSession)
        .filter(UserSession.id == token, UserSession.is_active.is_(True))
        .first()
    )
    if session_record is None:
        raise auth_error(401, "invalid_session", "Session token is invalid or inactive")

    now = utc_now()
    if now >= session_record.expires_at:
        session_record.is_active = False
        db.commit()
        raise auth_error(401, "session_expired", "Session token has expired")

    return session_record


async def get_current_session(
    authorization: Optional[str] = Header(default=None),
    db: DBSession = Depends(get_db),
) -> UserSession:
    """FastAPI dependency injecting the validated active Session record."""
    return await validate_session(authorization=authorization, db=db)
