"""Google OAuth 2.0 sign-in, callback, session refresh, and logout routes."""

from __future__ import annotations

import logging
import os
import re
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

from app.core.encryption import encrypt_secret
from app.database import get_db
from app.middleware.auth import auth_error, extract_bearer_token, get_current_session
from app.models.session import OAuthState, Session as UserSession, User, utc_now
from app.models.task import GoogleOAuthToken

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
OAUTH_SCOPES = ["openid", "email", "profile", GMAIL_READONLY_SCOPE]
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


def _is_valid_redirect_uri(redirect_uri: str) -> bool:
    """Check if redirect_uri is valid: exact match in list OR matches localhost regex."""
    allowed = _get_allowed_redirect_uris(
        os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/callback").strip()
    )
    
    # Exact match check
    if redirect_uri in allowed:
        return True
    
    # For localhost/127.0.0.1 with /auth.html path, allow ANY port
    localhost_pattern = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?/auth\.html$"
    if re.match(localhost_pattern, redirect_uri):
        return True
    
    return False


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
    # Allow Google to return different scopes (some might be optional/not granted)
    flow.code_verifier = None  # Will be set by caller if needed
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

    target_redirect_uri = (
        payload.redirect_uri.strip()
        if payload and payload.redirect_uri
        else default_redirect_uri
    )
    
    # Use dynamic validation that accepts any localhost port
    if not _is_valid_redirect_uri(target_redirect_uri):
        raise auth_error(
            400,
            "invalid_redirect_uri",
            "Requested redirect URI is not valid (must be localhost or in allowlist)",
        )

    state = secrets.token_urlsafe(32)
    flow = _build_google_flow(client_id, client_secret, target_redirect_uri)
    authorization_url, _ = flow.authorization_url(
        state=state,
        access_type="offline",
        include_granted_scopes="true",
        prompt="select_account consent",
    )

    # Extract code_verifier from flow for PKCE
    code_verifier = flow.code_verifier
    logger.info(f"🔐 PKCE code_verifier generated: {code_verifier[:20] if code_verifier else 'None'}...")

    try:
        _cleanup_expired_states(db)
        now = utc_now()
        db.add(
            OAuthState(
                state=state,
                redirect_uri=target_redirect_uri,
                code_verifier=code_verifier,
                created_at=now,
                expires_at=now + timedelta(minutes=STATE_TTL_MINUTES),
            )
        )
        db.commit()
        logger.info(f"✅ OAuth state stored: {state[:20]}... for redirect_uri: {target_redirect_uri}")
    except Exception as exc:
        db.rollback()
        logger.error(f"❌ Failed to store OAuth state: {exc}")
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
        logger.error(f"❌ OAuth denied: {error}")
        raise auth_error(400, "oauth_denied", f"Google authorization failed: {error}")

    if not code or not code.strip():
        logger.error("❌ Missing authorization code")
        raise auth_error(400, "missing_code", "Authorization code parameter is required")

    if not state or not state.strip():
        logger.error("❌ Missing state parameter")
        raise auth_error(400, "missing_state", "State parameter is required for CSRF protection")

    client_id, client_secret, _, expiry_days = _get_oauth_settings()
    logger.info(f"🔍 Callback received - state: {state[:20]}..., code: {code[:20]}...")

    # Strictly validate and consume single-use CSRF state token.
    now = utc_now()
    stored_state = (
        db.query(OAuthState).filter(OAuthState.state == state.strip()).first()
    )
    
    # Debug: log all states in DB
    all_states = db.query(OAuthState).all()
    logger.info(f"📋 Total states in DB: {len(all_states)}")
    for s in all_states:
        logger.info(f"   State: {s.state[:20]}..., Expires: {s.expires_at}, Now: {now}")
    
    if stored_state is None or stored_state.expires_at <= now:
        logger.error(f"❌ State not found or expired. Stored: {stored_state}, Now: {now}")
        if stored_state is not None:
            db.delete(stored_state)
            db.commit()
        raise auth_error(
            400,
            "invalid_state",
            "State token is invalid, expired, or already used",
        )

    logger.info(f"✅ State validated, redirect_uri: {stored_state.redirect_uri}")
    redirect_uri = stored_state.redirect_uri
    # Consume state immediately to prevent replay attacks.
    db.delete(stored_state)
    db.commit()
    logger.info("✅ State consumed")
    code_verifier = stored_state.code_verifier
    logger.info(f"🔐 Retrieved code_verifier: {code_verifier[:20] if code_verifier else 'None'}...")

    # Exchange authorization code for Google OIDC ID token.
    try:
        logger.info(f"🔄 Exchanging code for token with redirect_uri: {redirect_uri}")
        flow = _build_google_flow(client_id, client_secret, redirect_uri)
        # Restore the code_verifier for PKCE validation
        if code_verifier:
            flow.code_verifier = code_verifier
        # Disable strict scope validation - Google may return different scopes
        token_response = flow.fetch_token(code=code.strip(), skip_authorization_header=False)
        logger.info("✅ Token exchanged successfully")
    except Exception as exc:
        logger.error(f"❌ Failed to exchange code: {exc}")
        # Try again without strict scope validation
        try:
            logger.info("🔄 Retrying without strict scope validation...")
            flow = _build_google_flow(client_id, client_secret, redirect_uri)
            if code_verifier:
                flow.code_verifier = code_verifier
            flow.scopes = None  # Disable scope validation
            token_response = flow.fetch_token(code=code.strip())
            logger.info("✅ Token exchanged successfully (without scope validation)")
        except Exception as retry_exc:
            logger.error(f"❌ Retry failed: {retry_exc}")
            raise auth_error(
                400,
                "invalid_code",
                "Authorization code is invalid, expired, or already used",
            ) from retry_exc

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

        # Extract Google access/refresh tokens to store encrypted server-side for Gmail polling.
        access_token = None
        refresh_token = None
        token_expiry = None
        granted_scopes_str = " ".join(OAUTH_SCOPES)

        if isinstance(token_response, dict):
            access_token = token_response.get("access_token")
            refresh_token = token_response.get("refresh_token")
            expires_in = token_response.get("expires_in")
            if isinstance(expires_in, (int, float)) and expires_in > 0:
                token_expiry = utc_now() + timedelta(seconds=int(expires_in))
            if token_response.get("scope"):
                granted_scopes_str = str(token_response["scope"])

        if flow.credentials is not None:
            access_token = access_token or getattr(flow.credentials, "token", None)
            refresh_token = refresh_token or getattr(flow.credentials, "refresh_token", None)
            cred_expiry = getattr(flow.credentials, "expiry", None)
            if token_expiry is None and cred_expiry is not None:
                token_expiry = cred_expiry.replace(tzinfo=None)
            cred_scopes = getattr(flow.credentials, "scopes", None)
            if cred_scopes:
                granted_scopes_str = " ".join(cred_scopes)

        if access_token:
            existing_token = (
                db.query(GoogleOAuthToken)
                .filter(GoogleOAuthToken.user_id == user.id)
                .first()
            )
            encrypted_access = encrypt_secret(str(access_token))
            encrypted_refresh = encrypt_secret(str(refresh_token)) if refresh_token else None

            if existing_token is None:
                db.add(
                    GoogleOAuthToken(
                        user_id=user.id,
                        encrypted_access_token=encrypted_access,
                        encrypted_refresh_token=encrypted_refresh,
                        token_expiry=token_expiry,
                        scopes=granted_scopes_str,
                        needs_reconnect=False,
                        last_error=None,
                    )
                )
            else:
                existing_token.encrypted_access_token = encrypted_access
                if encrypted_refresh:
                    existing_token.encrypted_refresh_token = encrypted_refresh
                existing_token.token_expiry = token_expiry
                existing_token.scopes = granted_scopes_str
                existing_token.needs_reconnect = False
                existing_token.last_error = None
                existing_token.updated_at = utc_now()

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
    """Return the authenticated user's profile, session expiry, and Gmail scope status."""
    user = current_session.user
    token_record = user.google_token
    return {
        "user": {
            "email": user.email,
            "name": user.name,
            "picture_url": user.picture_url,
        },
        "expires_at": _format_iso_utc(current_session.expires_at),
        "granted_scopes": token_record.scope_list() if token_record else ["openid", "email", "profile"],
        "google_reconnect_required": bool(token_record.needs_reconnect) if token_record else False,
    }
