"""Google OAuth 2.0 sign-in, callback, session refresh, and logout routes."""

from __future__ import annotations

import os
import secrets
import uuid
from datetime import timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, Query
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from google_auth_oauthlib.flow import Flow
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from app.database import get_db
from app.middleware.auth import auth_error, extract_bearer_token, get_current_session
from app.models.session import OAuthState, Session as UserSession, User, utc_now

router = APIRouter(prefix="/auth", tags=["auth"])

OAUTH_SCOPES = ["openid", "email", "profile"]
STATE_TTL_MINUTES = 10


class SignInRequest(BaseModel):
    """Optional request payload allowing a pre-allowlisted redirect URI override."""

    redirect_uri: Optional[str] = None


def _get_oauth_settings() -> tuple[str, str, str, int]:
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    default_redirect_uri = os.getenv(
        "GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/callback"
    ).strip()
    expiry_days = int(os.getenv("SESSION_TOKEN_EXPIRY_DAYS", "30"))

    if not client_id or not client_secret:
        raise auth_error(
            500,
            "oauth_not_configured",
            "Google OAuth credentials are not configured on the server",
        )
    return client_id, client_secret, default_redirect_uri, expiry_days


def _get_allowed_redirect_uris(default_redirect_uri: str) -> List[str]:
    configured = [
        uri.strip()
        for uri in os.getenv("ALLOWED_OAUTH_REDIRECT_URIS", "").split(",")
        if uri.strip()
    ]
    if default_redirect_uri not in configured:
        configured.insert(0, default_redirect_uri)
    return configured


def _build_google_flow(client_id: str, client_secret: str, redirect_uri: str) -> Flow:
    """Create a Google OAuth 2.0 Web Application Flow."""
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/v2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect_uri],
            }
        },
        scopes=OAUTH_SCOPES,
    )
    flow.redirect_uri = redirect_uri
    return flow


def _format_iso_utc(dt) -> str:
    return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def _cleanup_expired_states(db: DBSession) -> None:
    now = utc_now()
    db.query(OAuthState).filter(OAuthState.expires_at <= now).delete()


def _verify_google_id_token(raw_token: str, client_id: str) -> Dict[str, Any]:
    """Cryptographically verify the Google OIDC ID token using Google's public keys."""
    if not raw_token or not isinstance(raw_token, str):
        raise ValueError("Missing ID token in Google token response")

    claims = google_id_token.verify_oauth2_token(
        raw_token,
        google_requests.Request(),
        audience=client_id,
    )
    issuer = claims.get("iss")
    if issuer not in ("accounts.google.com", "https://accounts.google.com"):
        raise ValueError("Unexpected ID token issuer")
    if not claims.get("sub") or not claims.get("email"):
        raise ValueError("ID token missing required identity claims")
    return claims


@router.post("/signin")
def auth_signin(
    payload: Optional[SignInRequest] = None,
    db: DBSession = Depends(get_db),
) -> Dict[str, str]:
    """Return the Google OAuth 2.0 consent URL with a single-use CSRF state token."""
    client_id, client_secret, default_redirect_uri, _ = _get_oauth_settings()
    allowed_redirects = _get_allowed_redirect_uris(default_redirect_uri)

    target_redirect_uri = (
        payload.redirect_uri.strip()
        if payload and payload.redirect_uri
        else default_redirect_uri
    )
    if target_redirect_uri not in allowed_redirects:
        raise auth_error(
            400,
            "invalid_redirect_uri",
            "Requested redirect URI is not in the server allowlist",
        )

    state = secrets.token_urlsafe(32)
    flow = _build_google_flow(client_id, client_secret, target_redirect_uri)
    authorization_url, _ = flow.authorization_url(
        state=state,
        access_type="online",
        include_granted_scopes="true",
        prompt="select_account",
    )

    try:
        _cleanup_expired_states(db)
        now = utc_now()
        db.add(
            OAuthState(
                state=state,
                redirect_uri=target_redirect_uri,
                created_at=now,
                expires_at=now + timedelta(minutes=STATE_TTL_MINUTES),
            )
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        raise auth_error(
            500,
            "state_storage_failed",
            "Unable to initialize OAuth sign-in state",
        ) from exc

    return {"redirect_url": authorization_url}


@router.get("/callback")
def auth_callback(
    code: Optional[str] = Query(default=None),
    state: Optional[str] = Query(default=None),
    error: Optional[str] = Query(default=None),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    """Validate CSRF state, exchange Google auth code, verify ID token, and issue an opaque session."""
    if error:
        raise auth_error(400, "oauth_denied", f"Google authorization failed: {error}")

    if not code or not code.strip():
        raise auth_error(400, "missing_code", "Authorization code parameter is required")

    if not state or not state.strip():
        raise auth_error(400, "missing_state", "State parameter is required for CSRF protection")

    client_id, client_secret, _, expiry_days = _get_oauth_settings()

    # Strictly validate and consume single-use CSRF state token.
    now = utc_now()
    stored_state = (
        db.query(OAuthState).filter(OAuthState.state == state.strip()).first()
    )
    if stored_state is None or stored_state.expires_at <= now:
        if stored_state is not None:
            db.delete(stored_state)
            db.commit()
        raise auth_error(
            400,
            "invalid_state",
            "State token is invalid, expired, or already used",
        )

    redirect_uri = stored_state.redirect_uri
    # Consume state immediately to prevent replay attacks.
    db.delete(stored_state)
    db.commit()

    # Exchange authorization code for Google OIDC ID token.
    try:
        flow = _build_google_flow(client_id, client_secret, redirect_uri)
        token_response = flow.fetch_token(code=code.strip())
    except Exception as exc:
        raise auth_error(
            400,
            "invalid_code",
            "Authorization code is invalid, expired, or already used",
        ) from exc

    raw_id_token = None
    if isinstance(token_response, dict):
        raw_id_token = token_response.get("id_token")
    if not raw_id_token and flow.credentials is not None:
        raw_id_token = getattr(flow.credentials, "id_token", None)

    try:
        claims = _verify_google_id_token(raw_id_token, client_id)
    except Exception as exc:
        raise auth_error(
            500,
            "id_token_verification_failed",
            "Failed to verify Google identity token",
        ) from exc

    google_sub = str(claims["sub"])
    email = str(claims["email"]).strip().lower()
    name = str(claims.get("name") or email).strip()
    picture_url = claims.get("picture")

    try:
        user = db.query(User).filter(User.google_id == google_sub).first()
        if user is None:
            user = User(
                google_id=google_sub,
                email=email,
                name=name,
                picture_url=picture_url,
            )
            db.add(user)
            db.flush()
        else:
            user.email = email
            user.name = name
            user.picture_url = picture_url
            user.updated_at = utc_now()
            db.flush()

        created_at = utc_now()
        expires_at = created_at + timedelta(days=expiry_days)
        session_id = str(uuid.uuid4())
        new_session = UserSession(
            id=session_id,
            user_id=user.id,
            created_at=created_at,
            expires_at=expires_at,
            is_active=True,
        )
        db.add(new_session)
        db.commit()
    except Exception as exc:
        db.rollback()
        raise auth_error(
            500,
            "session_creation_failed",
            "Failed to persist user session",
        ) from exc

    return {
        "session_token": session_id,
        "user": {
            "email": user.email,
            "name": user.name,
            "picture_url": user.picture_url,
        },
        "expires_at": _format_iso_utc(expires_at),
    }


@router.post("/refresh")
def auth_refresh(
    current_session: UserSession = Depends(get_current_session),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    """Rotate an active opaque session token for a new 30-day session and deactivate the old one."""
    expiry_days = int(os.getenv("SESSION_TOKEN_EXPIRY_DAYS", "30"))
    created_at = utc_now()
    new_expires_at = created_at + timedelta(days=expiry_days)
    new_session_id = str(uuid.uuid4())

    try:
        replacement = UserSession(
            id=new_session_id,
            user_id=current_session.user_id,
            created_at=created_at,
            expires_at=new_expires_at,
            is_active=True,
        )
        db.add(replacement)
        db.flush()

        current_session.is_active = False
        db.commit()
    except Exception as exc:
        db.rollback()
        raise auth_error(
            500,
            "session_refresh_failed",
            "Failed to extend user session",
        ) from exc

    user = current_session.user
    return {
        "session_token": new_session_id,
        "expires_at": _format_iso_utc(new_expires_at),
        "user": {
            "email": user.email,
            "name": user.name,
            "picture_url": user.picture_url,
        },
    }


@router.post("/logout")
def auth_logout(
    authorization: Optional[str] = Header(default=None),
    db: DBSession = Depends(get_db),
) -> Dict[str, str]:
    """Revoke the caller's session by marking `is_active = False`."""
    token = extract_bearer_token(authorization)
    session_record = db.query(UserSession).filter(UserSession.id == token).first()

    if session_record is None:
        raise auth_error(404, "session_not_found", "Session not found")

    if not session_record.is_active or utc_now() >= session_record.expires_at:
        if session_record.is_active:
            session_record.is_active = False
            db.commit()
        raise auth_error(401, "invalid_session", "Session token is invalid or expired")

    try:
        session_record.is_active = False
        db.commit()
    except Exception as exc:
        db.rollback()
        raise auth_error(
            500,
            "logout_failed",
            "Failed to revoke user session",
        ) from exc

    return {"message": "Logged out successfully"}


@router.get("/me")
def auth_me(
    current_session: UserSession = Depends(get_current_session),
) -> Dict[str, Any]:
    """Return the authenticated user's profile and current session expiry."""
    user = current_session.user
    return {
        "user": {
            "email": user.email,
            "name": user.name,
            "picture_url": user.picture_url,
        },
        "expires_at": _format_iso_utc(current_session.expires_at),
    }
