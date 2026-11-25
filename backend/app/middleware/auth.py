"""Reusable Bearer and HttpOnly cookie session validation middleware and FastAPI dependencies."""

from __future__ import annotations

from typing import Optional

from fastapi import Depends, Header, HTTPException, Request, Response
from sqlalchemy.orm import Session as DBSession

from app.database import get_db
from app.models.session import Session as UserSession
from app.models.session import utc_now

SESSION_COOKIE_NAME = "joshu_session"
PROFILES_COOKIE_NAME = "joshu_profiles"
_MAX_PROFILES_COOKIE_SESSIONS = 6
_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_ALLOWED_CSRF_HEADERS = {"fetch", "xmlhttprequest"}


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


def _is_https_request(request: Request) -> bool:
    forwarded = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    if forwarded in ("http", "https"):
        return forwarded == "https"
    return request.url.scheme == "https"


def _format_named_cookie_header(name: str, value: str, max_age: int, is_https: bool) -> str:
    parts = [
        f"{name}={value}",
        "Path=/",
        f"Max-Age={max_age}",
        "HttpOnly",
    ]
    if is_https:
        parts.extend(["Secure", "SameSite=None", "Partitioned"])
    else:
        parts.append("SameSite=Lax")
    return "; ".join(parts)


def _format_cookie_header(value: str, max_age: int, is_https: bool) -> str:
    return _format_named_cookie_header(
        name=SESSION_COOKIE_NAME,
        value=value,
        max_age=max_age,
        is_https=is_https,
    )


def get_profile_session_ids(
    request: Request,
    include_session_id: Optional[str] = None,
    exclude_session_id: Optional[str] = None,
) -> list[str]:
    """Return deduplicated session IDs stored in the browser's multi-profile cookies."""
    ordered: list[str] = []
    if include_session_id and include_session_id.strip():
        ordered.append(include_session_id.strip())

    active_cookie = (request.cookies.get(SESSION_COOKIE_NAME) or "").strip()
    if active_cookie and active_cookie not in ordered:
        ordered.append(active_cookie)

    raw_profiles = (request.cookies.get(PROFILES_COOKIE_NAME) or "").strip()
    if raw_profiles:
        for part in raw_profiles.split(","):
            token = part.strip()
            if token and token not in ordered:
                ordered.append(token)

    if exclude_session_id:
        excluded = exclude_session_id.strip()
        ordered = [tok for tok in ordered if tok != excluded]

    return ordered[:_MAX_PROFILES_COOKIE_SESSIONS]


def set_session_cookie(
    response: Response,
    request: Request,
    session_id: str,
    max_age_seconds: int,
) -> None:
    """Emit HttpOnly session and multi-profile cookies compatible with localhost HTTP and HTTPS iframes."""
    is_https = _is_https_request(request)
    clamped_age = max(0, int(max_age_seconds))
    header_value = _format_cookie_header(
        value=session_id,
        max_age=clamped_age,
        is_https=is_https,
    )
    response.headers.append("set-cookie", header_value)

    profile_ids = get_profile_session_ids(request=request, include_session_id=session_id)
    if profile_ids:
        profiles_header = _format_named_cookie_header(
            name=PROFILES_COOKIE_NAME,
            value=",".join(profile_ids),
            max_age=clamped_age,
            is_https=is_https,
        )
        response.headers.append("set-cookie", profiles_header)


def clear_session_cookie(
    response: Response,
    request: Request,
    removed_session_id: Optional[str] = None,
) -> None:
    """Clear the active HttpOnly session cookie and remove the revoked session from joshu_profiles."""
    is_https = _is_https_request(request)
    header_value = _format_cookie_header(
        value="",
        max_age=0,
        is_https=is_https,
    )
    response.headers.append("set-cookie", header_value)

    if removed_session_id:
        remaining = get_profile_session_ids(
            request=request,
            exclude_session_id=removed_session_id,
        )
        profiles_header = _format_named_cookie_header(
            name=PROFILES_COOKIE_NAME,
            value=",".join(remaining),
            max_age=30 * 86400 if remaining else 0,
            is_https=is_https,
        )
        response.headers.append("set-cookie", profiles_header)


def verify_cookie_csrf(request: Request) -> None:
    """Require a non-simple X-Requested-With header on cookie-authenticated mutations."""
    if request.method.upper() not in _MUTATING_METHODS:
        return
    requested_with = (request.headers.get("x-requested-with") or "").strip().lower()
    if requested_with not in _ALLOWED_CSRF_HEADERS:
        raise auth_error(
            403,
            "csrf_header_required",
            "Missing required X-Requested-With header for cookie-authenticated request",
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


def resolve_session_token(
    request: Request,
    authorization: Optional[str],
) -> tuple[str, bool]:
    """Extract session token from Authorization Bearer header or HttpOnly cookie."""
    if authorization:
        return extract_bearer_token(authorization), False

    cookie_token = (request.cookies.get(SESSION_COOKIE_NAME) or "").strip()
    if cookie_token:
        return cookie_token, True

    raise auth_error(401, "missing_authorization", "Authorization header or session cookie is required")


async def validate_session_token(token: str, db: DBSession) -> UserSession:
    """Validate an opaque session token string against the database."""
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


async def validate_session(authorization: Optional[str], db: DBSession) -> UserSession:
    """
    Validate an opaque Bearer session token against the database.

    Raises HTTPException(401) if the token is missing, malformed, inactive,
    unknown, or expired.
    """
    token = extract_bearer_token(authorization)
    return await validate_session_token(token=token, db=db)


async def get_current_session(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    db: DBSession = Depends(get_db),
) -> UserSession:
    """FastAPI dependency injecting the validated active Session record."""
    token, via_cookie = resolve_session_token(request=request, authorization=authorization)
    if via_cookie:
        verify_cookie_csrf(request)
    return await validate_session_token(token=token, db=db)
