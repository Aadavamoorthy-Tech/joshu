"""Zero-dependency Google OAuth 2.0 & Gmail REST API polling service.

Uses only the Python 3 standard library (`urllib.request`, `ssl`, `json`) plus
the real Phase 2 `invite_parser` module. Loads Google Cloud Console credentials
from environment variables (or local `.env` / `backend/.env`) — never hardcodes
secrets and always prompts account selection (`prompt=select_account consent`)
so any user can sign in with any Google/Gmail account.
"""

from __future__ import annotations

import base64
import json
import os
import re
import ssl
import sys
import uuid
from datetime import datetime, timedelta, timezone
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

# Reuse the real Phase 2 invitation parser from backend/.
_ROOT_DIR = Path(__file__).resolve().parent.parent
_BACKEND_DIR = _ROOT_DIR / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.services.invite_parser import (  # noqa: E402
    _decode_base64url,
    _extract_headers,
    _strip_html,
    _walk_mime_parts,
    parse_gmail_invite_message,
    sanitize_event_url,
)

GOOGLE_AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URI = "https://www.googleapis.com/oauth2/v3/userinfo"
GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"

GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GOOGLE_OAUTH_SCOPES = ("openid", "email", "profile", GMAIL_READONLY_SCOPE)

_PLACEHOLDER_PREFIXES = ("YOUR_", "REPLACE_", "<")
_URL_PATTERN = re.compile(r"https://[^\s<>\"')\]}]+", re.IGNORECASE)


class GoogleOAuthConfigError(RuntimeError):
    """Raised when Google Cloud Console OAuth credentials are not configured."""


class GoogleOAuthError(RuntimeError):
    """Raised when Google OAuth token exchange, refresh, or Gmail API fails."""


class GoogleTokenExpiredError(GoogleOAuthError):
    """Raised when the signed-in Google access/refresh token is no longer valid."""


def load_local_env_files() -> None:
    """Load key=value pairs from `.env` and `backend/.env` into os.environ if not already set."""
    candidates = (_ROOT_DIR / ".env", _BACKEND_DIR / ".env")
    for env_path in candidates:
        if not env_path.is_file():
            continue
        try:
            for raw_line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                # Strip unquoted inline comments (e.g. `KEY=value # comment`).
                if value and value[0] not in ('"', "'") and " #" in value:
                    value = value.split(" #", 1)[0].strip()
                value = value.strip('"').strip("'").strip()
                if not key or key in os.environ:
                    continue
                if any(value.upper().startswith(prefix) for prefix in _PLACEHOLDER_PREFIXES):
                    continue
                if value:
                    os.environ[key] = value
        except OSError:
            continue


def _clean_env_secret(name: str) -> str:
    val = os.getenv(name, "").strip().strip('"').strip("'").strip()
    if not val or any(val.upper().startswith(prefix) for prefix in _PLACEHOLDER_PREFIXES):
        return ""
    return val


def is_valid_google_client_id(client_id: str) -> bool:
    """Verify the value matches Google OAuth 2.0 Client ID format (*.apps.googleusercontent.com)."""
    return bool(client_id) and client_id.endswith(".apps.googleusercontent.com") and " " not in client_id


def get_google_oauth_config(request_origin: str) -> Dict[str, Any]:
    """Return non-secret Google OAuth configuration status and resolved callback URI."""
    load_local_env_files()
    client_id = _clean_env_secret("GOOGLE_CLIENT_ID")
    client_secret = _clean_env_secret("GOOGLE_CLIENT_SECRET")

    app_url = _clean_env_secret("APP_URL").rstrip("/")
    explicit_redirect = _clean_env_secret("GOOGLE_APP_REDIRECT_URI")

    is_explicit_local = bool(
        explicit_redirect
        and ("localhost" in explicit_redirect.lower() or "127.0.0.1" in explicit_redirect)
    )

    if explicit_redirect and not (app_url and is_explicit_local):
        redirect_uri = explicit_redirect
    elif app_url:
        redirect_uri = f"{app_url}/auth/google/callback"
    else:
        origin = request_origin.rstrip("/")
        redirect_uri = f"{origin}/auth/google/callback"

    return {
        "configured": bool(is_valid_google_client_id(client_id) and client_secret),
        "redirect_uri": redirect_uri,
    }


def _require_google_credentials(request_origin: str) -> Tuple[str, str, str]:
    load_local_env_files()
    client_id = _clean_env_secret("GOOGLE_CLIENT_ID")
    client_secret = _clean_env_secret("GOOGLE_CLIENT_SECRET")
    cfg = get_google_oauth_config(request_origin)
    if not client_id and not client_secret:
        raise GoogleOAuthConfigError(
            "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are not set yet in this environment. "
            f"Add them in Settings → Secrets (or .env / backend/.env locally) and register {cfg['redirect_uri']} "
            "as an Authorized Redirect URI in Google Cloud Console."
        )
    if not client_id:
        raise GoogleOAuthConfigError(
            "GOOGLE_CLIENT_ID is missing. Add your Web application OAuth 2.0 Client ID "
            "(ending in .apps.googleusercontent.com) in Settings → Secrets or .env."
        )
    if client_id.startswith("GOCSPX-"):
        raise GoogleOAuthConfigError(
            "GOOGLE_CLIENT_ID starts with GOCSPX-, which is a Client Secret — it looks like "
            "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET were swapped."
        )
    if client_id.startswith("AIza"):
        raise GoogleOAuthConfigError(
            "GOOGLE_CLIENT_ID starts with AIza, which is a Google API Key. Sign in with Google requires an "
            "OAuth 2.0 Client ID (Application type: Web application, ending in .apps.googleusercontent.com)."
        )
    if not is_valid_google_client_id(client_id):
        raise GoogleOAuthConfigError(
            "GOOGLE_CLIENT_ID must be a full Google OAuth 2.0 Web Client ID ending in "
            ".apps.googleusercontent.com (check for missing suffix or extra characters in Settings → Secrets)."
        )
    if not client_secret:
        raise GoogleOAuthConfigError(
            "GOOGLE_CLIENT_SECRET is missing. Add the matching OAuth 2.0 Client Secret in Settings → Secrets or .env."
        )
    return client_id, client_secret, str(cfg["redirect_uri"])


def _resolve_allowed_redirect_uri(
    request_origin: str,
    default_redirect_uri: str,
    requested_redirect_uri: Optional[str] = None,
) -> str:
    """Use requested_redirect_uri only for local same-origin callback paths; hosted preview always uses APP_URL."""
    app_url = _clean_env_secret("APP_URL")
    if app_url or not requested_redirect_uri:
        return default_redirect_uri

    candidate = requested_redirect_uri.strip()
    origin = request_origin.rstrip("/")
    allowed_paths = ("/auth.html", "/task-dashboard.html", "/auth/google/callback")
    for path in allowed_paths:
        if candidate == f"{origin}{path}":
            return candidate
    return default_redirect_uri


def build_google_authorization_url(
    request_origin: str,
    state: str,
    requested_redirect_uri: Optional[str] = None,
) -> Tuple[str, str]:
    """Build Google OAuth 2.0 consent URL that always prompts account selection."""
    client_id, _, default_redirect_uri = _require_google_credentials(request_origin)
    redirect_uri = _resolve_allowed_redirect_uri(
        request_origin=request_origin,
        default_redirect_uri=default_redirect_uri,
        requested_redirect_uri=requested_redirect_uri,
    )
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(GOOGLE_OAUTH_SCOPES),
        "state": state,
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "select_account consent",
    }
    return f"{GOOGLE_AUTH_URI}?{urlencode(params)}", redirect_uri


def _http_json(
    url: str,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    form_data: Optional[Dict[str, str]] = None,
    timeout: int = 12,
) -> Tuple[int, Dict[str, Any]]:
    req_headers = {"Accept": "application/json"}
    if headers:
        req_headers.update(headers)

    body: Optional[bytes] = None
    if form_data is not None:
        body = urlencode(form_data).encode("utf-8")
        req_headers["Content-Type"] = "application/x-www-form-urlencoded"

    req = Request(url, data=body, headers=req_headers, method=method)
    ssl_ctx = ssl.create_default_context()
    try:
        with urlopen(req, timeout=timeout, context=ssl_ctx) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            parsed = json.loads(raw) if raw else {}
            return resp.status, parsed if isinstance(parsed, dict) else {}
    except HTTPError as exc:
        raw_err = exc.read().decode("utf-8", errors="replace")
        try:
            parsed_err = json.loads(raw_err)
            if not isinstance(parsed_err, dict):
                parsed_err = {"error": raw_err}
        except Exception:
            parsed_err = {"error": raw_err}
        return exc.code, parsed_err
    except URLError as exc:
        raise GoogleOAuthError("Could not reach Google services. Check your internet connection.") from exc


def exchange_google_authorization_code(
    code: str,
    redirect_uri: str,
    request_origin: str,
) -> Dict[str, Any]:
    """Exchange a Google authorization code for access_token and optional refresh_token."""
    client_id, client_secret, _ = _require_google_credentials(request_origin)
    status, payload = _http_json(
        GOOGLE_TOKEN_URI,
        method="POST",
        form_data={
            "code": code.strip(),
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
    )
    if status != 200 or not payload.get("access_token"):
        err_desc = payload.get("error_description") or payload.get("error") or "Token exchange failed."
        raise GoogleOAuthError(f"Google sign-in failed: {err_desc}")

    expires_in = int(payload.get("expires_in") or 3600)
    return {
        "access_token": str(payload["access_token"]),
        "refresh_token": str(payload["refresh_token"]) if payload.get("refresh_token") else None,
        "token_expiry": datetime.now(timezone.utc) + timedelta(seconds=expires_in),
        "scope": str(payload.get("scope") or " ".join(GOOGLE_OAUTH_SCOPES)),
    }


def refresh_google_access_token(
    refresh_token: str,
    request_origin: str,
) -> Dict[str, Any]:
    """Refresh an expired Google OAuth access token using the stored refresh token."""
    client_id, client_secret, _ = _require_google_credentials(request_origin)
    status, payload = _http_json(
        GOOGLE_TOKEN_URI,
        method="POST",
        form_data={
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
        },
    )
    if status != 200 or not payload.get("access_token"):
        raise GoogleTokenExpiredError(
            "Your Google authorization expired or was revoked. Please sign in again."
        )

    expires_in = int(payload.get("expires_in") or 3600)
    return {
        "access_token": str(payload["access_token"]),
        "token_expiry": datetime.now(timezone.utc) + timedelta(seconds=expires_in),
    }


def fetch_google_userinfo(access_token: str) -> Dict[str, Any]:
    """Fetch the signed-in Google account's email, name, and avatar."""
    status, payload = _http_json(
        GOOGLE_USERINFO_URI,
        method="GET",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    if status == 401:
        raise GoogleTokenExpiredError("Google session expired. Please sign in again.")
    if status != 200 or not payload.get("email"):
        raise GoogleOAuthError("Could not read signed-in Google account profile.")

    return {
        "email": str(payload["email"]).strip().lower(),
        "name": str(payload.get("name") or payload["email"]).strip(),
        "picture_url": str(payload.get("picture") or "").strip() or None,
    }


def _iso_utc(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    else:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _find_ics_attachment_ids(payload: Dict[str, Any]) -> List[str]:
    attachment_ids: List[str] = []

    def _visit(part: Dict[str, Any]) -> None:
        mime_type = str(part.get("mimeType") or "").lower()
        filename = str(part.get("filename") or "").lower()
        body = part.get("body") or {}
        if (
            (mime_type in ("text/calendar", "application/ics") or filename.endswith(".ics"))
            and not body.get("data")
            and body.get("attachmentId")
        ):
            attachment_ids.append(str(body["attachmentId"]))
        for child in part.get("parts") or []:
            if isinstance(child, dict):
                _visit(child)

    _visit(payload)
    return attachment_ids


def parse_gmail_api_message_to_task(
    full_message: Dict[str, Any],
    account_email: str,
    extra_ics_payloads: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    """Normalize a Gmail API `messages.get(format='full')` dict into a Joshu task.

    Calendar invitations are parsed via `parse_gmail_invite_message`; regular inbox
    emails are safely normalized into `source='email'` tasks so the user immediately
    sees real messages from their signed-in Gmail inbox.
    """
    msg_id = str(full_message.get("id") or "").strip()
    if not msg_id:
        return None

    now_iso = _iso_utc(datetime.now(timezone.utc))
    payload = full_message.get("payload") or {}
    headers = _extract_headers(payload)

    received_dt: Optional[datetime] = None
    if headers.get("date"):
        try:
            dt = parsedate_to_datetime(headers["date"])
            received_dt = dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt
        except (TypeError, ValueError):
            received_dt = None

    extracted = parse_gmail_invite_message(full_message, extra_ics_payloads=extra_ics_payloads)
    if extracted is not None:
        return {
            "id": str(uuid.uuid4()),
            "account_email": account_email,
            "external_message_id": extracted.external_message_id,
            "title": extracted.title,
            "description": extracted.description,
            "snippet": re.sub(r"\s+", " ", extracted.description).strip()[:220],
            "scheduled_for": _iso_utc(extracted.scheduled_for or received_dt),
            "source": "calendar" if extracted.source == "calendar" else "email",
            "is_meeting_invite": True,
            "status": "pending",
            "organizer": extracted.organizer or headers.get("from") or "Unknown Sender",
            "attendees": extracted.attendees,
            "calendar_event_link": extracted.calendar_event_link,
            "raw_data": extracted.raw_data,
            "created_at": now_iso,
            "updated_at": now_iso,
            "approved_at": None,
            "rejected_at": None,
            "rejection_reason": None,
            "approved_by_user": False,
        }

    # Regular inbox email (non-calendar invite)
    parts = _walk_mime_parts(payload)
    plain_text = "\n".join(parts["plain"]).strip()
    html_text = "\n".join(_strip_html(h) for h in parts["html"]).strip()
    clean_body = plain_text or html_text or str(full_message.get("snippet") or "").strip()
    summary = clean_body[:1500].strip() if clean_body else "No message body."
    snippet = re.sub(r"\s+", " ", summary).strip()[:220]

    subject = (headers.get("subject") or "(No Subject)")[:500]
    sender = headers.get("from") or "Unknown Sender"

    recipients: List[str] = []
    for key in ("to", "cc"):
        raw_addr = headers.get(key)
        if not raw_addr:
            continue
        for _, addr in getaddresses([raw_addr]):
            normalized = addr.strip().lower()
            if normalized and "@" in normalized and normalized not in recipients:
                recipients.append(normalized)

    first_safe_url: Optional[str] = None
    for candidate in _URL_PATTERN.findall(plain_text + "\n" + "\n".join(parts["html"])):
        safe = sanitize_event_url(candidate)
        if safe:
            first_safe_url = safe
            break

    return {
        "id": str(uuid.uuid4()),
        "account_email": account_email,
        "external_message_id": msg_id,
        "title": subject,
        "description": summary,
        "snippet": snippet,
        "scheduled_for": _iso_utc(received_dt),
        "source": "email",
        "is_meeting_invite": False,
        "status": "pending",
        "organizer": sender,
        "attendees": recipients,
        "calendar_event_link": first_safe_url,
        "raw_data": {
            "gmail_message_id": msg_id,
            "gmail_thread_id": full_message.get("threadId"),
            "subject": subject,
            "from": sender,
            "date": headers.get("date"),
        },
        "created_at": now_iso,
        "updated_at": now_iso,
        "approved_at": None,
        "rejected_at": None,
        "rejection_reason": None,
        "approved_by_user": False,
    }


def fetch_gmail_api_inbox_messages(
    access_token: str,
    account_email: str,
    max_messages: int = 20,
) -> List[Dict[str, Any]]:
    """Fetch recent INBOX messages for the signed-in Google account via Gmail REST API."""
    auth_headers = {"Authorization": f"Bearer {access_token}"}
    list_url = f"{GMAIL_API_BASE}/messages?{urlencode({'labelIds': 'INBOX', 'maxResults': max_messages})}"
    status, list_payload = _http_json(list_url, method="GET", headers=auth_headers)

    if status == 401:
        raise GoogleTokenExpiredError("Google access token expired. Please sign in again.")
    if status == 403:
        raise GoogleOAuthError(
            "Gmail API returned 403 Forbidden. Ensure the Gmail API is enabled in Google Cloud Console "
            "and that you granted Gmail read access on the consent screen."
        )
    if status != 200:
        raise GoogleOAuthError(f"Gmail API request failed (HTTP {status}).")

    stubs = list_payload.get("messages") or []
    if not stubs:
        fallback_url = (
            f"{GMAIL_API_BASE}/messages?"
            f"{urlencode({'q': '-in:trash -in:spam', 'maxResults': max_messages})}"
        )
        fb_status, fb_payload = _http_json(fallback_url, method="GET", headers=auth_headers)
        if fb_status == 200:
            stubs = fb_payload.get("messages") or []
    tasks: List[Dict[str, Any]] = []

    for stub in stubs:
        msg_id = str(stub.get("id") or "").strip()
        if not msg_id:
            continue
        msg_url = f"{GMAIL_API_BASE}/messages/{msg_id}?format=full"
        m_status, full_msg = _http_json(msg_url, method="GET", headers=auth_headers)
        if m_status == 401:
            raise GoogleTokenExpiredError("Google access token expired. Please sign in again.")
        if m_status != 200:
            continue

        extra_ics: List[str] = []
        for att_id in _find_ics_attachment_ids(full_msg.get("payload") or {}):
            att_url = f"{GMAIL_API_BASE}/messages/{msg_id}/attachments/{att_id}"
            a_status, att_payload = _http_json(att_url, method="GET", headers=auth_headers)
            if a_status == 200 and att_payload.get("data"):
                extra_ics.append(_decode_base64url(str(att_payload["data"])))

        task = parse_gmail_api_message_to_task(
            full_message=full_msg,
            account_email=account_email,
            extra_ics_payloads=extra_ics,
        )
        if task is not None:
            tasks.append(task)

    return tasks
