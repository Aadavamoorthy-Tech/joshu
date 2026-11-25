"""Background Gmail polling worker and on-demand invite sync service."""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import getaddresses, parsedate_to_datetime
from typing import Any, Callable, Dict, List, Optional

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build as build_google_service
from googleapiclient.errors import HttpError
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.encryption import decrypt_secret, encrypt_secret
from app.database import SessionLocal
from app.models.session import Session as UserSession, User, utc_now
from app.models.task import GoogleOAuthToken, Task
from app.services.email_analyzer import (
    EmailAnalysisError,
    analyze_email_smart,
    analyze_email_with_gemini,
    build_instant_analysis,
    is_ai_configured,
)
from app.services.invite_parser import (
    _extract_headers,
    _strip_html,
    _walk_mime_parts,
    parse_gmail_invite_message,
    sanitize_event_url,
)

logger = logging.getLogger("joshu.gmail_poller")

DEFAULT_POLL_INTERVAL_MINUTES = 1
DEFAULT_POLL_INTERVAL_SECONDS = 20
BACKGROUND_RETRY_SECONDS = 15
DEFAULT_MAX_MESSAGES_PER_POLL = 25
DEFAULT_GMAIL_QUERY = "in:inbox"
FALLBACK_GMAIL_QUERY = "-in:trash -in:spam"
_URL_PATTERN = re.compile(r"https://[^\s<>\"')\]}]+", re.IGNORECASE)
_USER_LOCKS_GUARD = threading.Lock()
_USER_LOCKS: Dict[int, threading.Lock] = {}


def _get_user_lock(user_id: int) -> threading.Lock:
    with _USER_LOCKS_GUARD:
        lock = _USER_LOCKS.get(user_id)
        if lock is None:
            lock = threading.Lock()
            _USER_LOCKS[user_id] = lock
        return lock


def is_user_sync_running(user_id: int) -> bool:
    """Return True if a sync/analysis cycle is already running for this user."""
    return _get_user_lock(user_id).locked()


class GmailPollingError(Exception):
    """Base error raised during Gmail polling."""


class GoogleTokenExpiredError(GmailPollingError):
    """Raised when a user's Google OAuth token is expired/revoked and needs re-consent."""


class GmailScopeMissingError(GmailPollingError):
    """Raised when the user has not yet granted gmail.readonly scope."""


class GmailApiError(GmailPollingError):
    """Raised when Gmail API calls fail due to network errors or upstream outages."""


@dataclass(frozen=True)
class SyncResult:
    """Summary of a single user's Gmail polling run."""

    user_id: int
    fetched_messages: int
    created_tasks: int
    skipped_duplicates: int
    ignored_non_invites: int
    synced_at: str
    analyzed_tasks: int = 0


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def get_poll_interval_minutes() -> int:
    try:
        minutes = int(os.getenv("GMAIL_POLL_INTERVAL_MINUTES", str(DEFAULT_POLL_INTERVAL_MINUTES)))
        return max(1, minutes)
    except ValueError:
        return DEFAULT_POLL_INTERVAL_MINUTES


def get_max_messages_per_poll() -> int:
    try:
        limit = int(os.getenv("GMAIL_MAX_MESSAGES_PER_POLL", str(DEFAULT_MAX_MESSAGES_PER_POLL)))
        return max(1, min(limit, 100))
    except ValueError:
        return DEFAULT_MAX_MESSAGES_PER_POLL


def is_polling_enabled() -> bool:
    return _env_bool("GMAIL_POLLING_ENABLED", True)


def _decode_attachment_data(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8", errors="replace")


def _find_ics_attachment_ids(payload: Dict[str, Any]) -> List[str]:
    """Find attachment IDs for `.ics` or `text/calendar` MIME parts whose body wasn't inlined."""
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


def _build_google_credentials(token_record: GoogleOAuthToken, db: DBSession) -> Credentials:
    """Decrypt stored Google tokens, refresh if expired, and persist updated credentials."""
    if token_record.needs_reconnect:
        raise GoogleTokenExpiredError(
            "Google account authorization has expired. Please sign in again to reconnect Gmail."
        )

    if not token_record.has_gmail_readonly():
        raise GmailScopeMissingError(
            "Gmail read access (gmail.readonly) has not been granted. Please re-authorize."
        )

    try:
        access_token = decrypt_secret(token_record.encrypted_access_token)
        refresh_token = (
            decrypt_secret(token_record.encrypted_refresh_token)
            if token_record.encrypted_refresh_token
            else None
        )
    except ValueError as exc:
        token_record.needs_reconnect = True
        token_record.last_error = "Stored OAuth credentials could not be decrypted"
        db.commit()
        raise GoogleTokenExpiredError(
            "Stored Google credentials are no longer valid. Please sign in again."
        ) from exc

    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()

    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id or None,
        client_secret=client_secret or None,
        scopes=token_record.scope_list(),
    )
    if token_record.token_expiry is not None:
        creds.expiry = token_record.token_expiry

    now = utc_now()
    needs_refresh = (
        token_record.token_expiry is not None
        and token_record.token_expiry <= now + timedelta(minutes=2)
    ) or creds.expired

    if needs_refresh:
        if not refresh_token or not client_id or not client_secret:
            token_record.needs_reconnect = True
            token_record.last_error = "Access token expired and no refresh token is available"
            db.commit()
            raise GoogleTokenExpiredError(
                "Google access token expired. Please sign in again to reconnect Gmail."
            )

        try:
            creds.refresh(GoogleAuthRequest())
        except RefreshError as exc:
            token_record.needs_reconnect = True
            token_record.last_error = "Google refresh token expired or revoked"
            db.commit()
            raise GoogleTokenExpiredError(
                "Google refresh token expired or was revoked. Please sign in again."
            ) from exc
        except Exception as exc:
            token_record.last_error = "Network error while refreshing Google token"
            db.commit()
            raise GmailApiError("Unable to reach Google to refresh credentials.") from exc

        token_record.encrypted_access_token = encrypt_secret(str(creds.token))
        if creds.expiry is not None:
            token_record.token_expiry = creds.expiry.replace(tzinfo=None)
        token_record.needs_reconnect = False
        token_record.last_error = None
        token_record.updated_at = utc_now()
        db.commit()

    return creds


def _default_gmail_service_factory(creds: Credentials) -> Any:
    return build_google_service("gmail", "v1", credentials=creds, cache_discovery=False)


def _parse_regular_inbox_email(full_message: Dict[str, Any], msg_id: str) -> Dict[str, Any]:
    """Normalize a standard non-invite Gmail inbox email into a sanitized pending task payload."""
    payload = full_message.get("payload") or {}
    headers = _extract_headers(payload)
    parts = _walk_mime_parts(payload)

    plain_text = "\n".join(parts["plain"]).strip()
    html_text = "\n".join(_strip_html(h) for h in parts["html"]).strip()
    clean_body = plain_text or html_text or str(full_message.get("snippet") or "").strip()
    description = clean_body[:2000].strip() if clean_body else "No message body."

    subject = (headers.get("subject") or "(No Subject)").strip()[:500]
    sender = (headers.get("from") or "Unknown Sender").strip()

    received_dt: Optional[datetime] = None
    if headers.get("date"):
        try:
            dt = parsedate_to_datetime(headers["date"])
            received_dt = dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt
        except (TypeError, ValueError):
            received_dt = None

    recipients: List[str] = []
    for hdr_key in ("to", "cc"):
        raw_addr = headers.get(hdr_key)
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
        "title": subject,
        "description": description,
        "scheduled_for": received_dt,
        "source": "email",
        "external_message_id": msg_id,
        "raw_data": {
            "gmail_message_id": msg_id,
            "gmail_thread_id": full_message.get("threadId"),
            "message_id_header": headers.get("message-id"),
            "reply_to": headers.get("reply-to") or sender,
            "organizer": sender,
            "attendees": recipients,
            "calendar_event_link": first_safe_url,
            "subject": subject,
            "date": headers.get("date"),
        },
    }


def _parse_iso_naive_utc(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).strip().replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except ValueError:
        return None


class GmailPollingService:
    """Polls Gmail inbox messages and calendar invitations for authenticated users."""

    def __init__(
        self,
        gmail_service_factory: Callable[[Credentials], Any] = _default_gmail_service_factory,
        query: Optional[str] = None,
        max_messages: Optional[int] = None,
        include_general_emails: Optional[bool] = None,
    ) -> None:
        self._gmail_service_factory = gmail_service_factory
        env_query = (os.getenv("GMAIL_POLL_QUERY") or "").strip()
        self._explicit_query = bool(query) or bool(env_query)
        self._query = (query or env_query or DEFAULT_GMAIL_QUERY).strip()
        self._max_messages = max_messages or get_max_messages_per_poll()
        self._include_general_emails = (
            include_general_emails
            if include_general_emails is not None
            else _env_bool("GMAIL_INCLUDE_GENERAL_EMAILS", True)
        )

    def poll_user_inbox(self, db: DBSession, user_id: int) -> SyncResult:
        """Fetch Gmail inbox emails and calendar invitations for a user and analyze them immediately."""
        user_lock = _get_user_lock(user_id)
        with user_lock:
            return self._poll_user_inbox_locked(db, user_id)

    def _poll_user_inbox_locked(self, db: DBSession, user_id: int) -> SyncResult:
        token_record = (
            db.query(GoogleOAuthToken)
            .filter(GoogleOAuthToken.user_id == user_id)
            .first()
        )
        if token_record is None:
            raise GoogleTokenExpiredError(
                "No Google Gmail credentials found for this account. Please sign in again."
            )

        creds = _build_google_credentials(token_record, db)
        used_query = self._query

        try:
            gmail = self._gmail_service_factory(creds)
            list_response = (
                gmail.users()
                .messages()
                .list(userId="me", q=used_query, maxResults=self._max_messages)
                .execute()
            )
            message_stubs = list_response.get("messages") or []

            # If default inbox query returns nothing (e.g., archived/All Mail messages only),
            # fall back to recent non-spam/non-trash mail so real emails are still surfaced.
            if not message_stubs and not self._explicit_query and used_query == DEFAULT_GMAIL_QUERY:
                used_query = FALLBACK_GMAIL_QUERY
                list_response = (
                    gmail.users()
                    .messages()
                    .list(userId="me", q=used_query, maxResults=self._max_messages)
                    .execute()
                )
                message_stubs = list_response.get("messages") or []
        except HttpError as exc:
            status_code = getattr(exc.resp, "status", None)
            if status_code == 401:
                token_record.needs_reconnect = True
                token_record.last_error = "Gmail API rejected credentials (401)"
                db.commit()
                raise GoogleTokenExpiredError(
                    "Google authorization expired. Please sign in again."
                ) from exc
            if status_code == 403:
                token_record.last_error = "Gmail API access denied (403)"
                db.commit()
                raise GmailScopeMissingError(
                    "Gmail API access was denied (403). Ensure the Gmail API is enabled in Google Cloud Console and gmail.readonly permission is granted."
                ) from exc
            token_record.last_error = f"Gmail API HTTP error ({status_code})"
            db.commit()
            raise GmailApiError("Gmail API temporarily unavailable.") from exc
        except Exception as exc:
            token_record.last_error = "Network error while contacting Gmail API"
            db.commit()
            raise GmailApiError("Network error while polling Gmail.") from exc

        fetched_count = len(message_stubs)
        created_count = 0
        skipped_duplicates = 0
        ignored_non_invites = 0

        existing_ids = {
            row[0]
            for row in db.query(Task.external_message_id)
            .filter(
                Task.user_id == user_id,
                Task.external_message_id.isnot(None),
            )
            .all()
        }

        user_record = db.query(User).filter(User.id == user_id).first()
        user_name = user_record.name if user_record else None
        user_email = user_record.email if user_record else None
        ai_enabled = is_ai_configured()

        for stub in message_stubs:
            msg_id = str(stub.get("id") or "").strip()
            if not msg_id:
                continue
            if msg_id in existing_ids:
                skipped_duplicates += 1
                continue

            try:
                full_message = (
                    gmail.users()
                    .messages()
                    .get(userId="me", id=msg_id, format="full")
                    .execute()
                )
            except Exception:
                # Skip a single transient message fetch failure without aborting the batch.
                logger.warning("Skipping Gmail message %s due to fetch error", msg_id)
                continue

            payload = full_message.get("payload") or {}
            msg_headers = _extract_headers(payload)
            extra_ics: List[str] = []
            for attachment_id in _find_ics_attachment_ids(payload):
                try:
                    att = (
                        gmail.users()
                        .messages()
                        .attachments()
                        .get(userId="me", messageId=msg_id, id=attachment_id)
                        .execute()
                    )
                    if att.get("data"):
                        extra_ics.append(_decode_attachment_data(str(att["data"])))
                except Exception:
                    logger.warning("Failed to fetch ICS attachment for message %s", msg_id)

            extracted = parse_gmail_invite_message(full_message, extra_ics_payloads=extra_ics)
            now = utc_now()
            if extracted is not None:
                raw_data = dict(extracted.raw_data or {})
                raw_data.setdefault("gmail_message_id", msg_id)
                raw_data.setdefault("gmail_thread_id", full_message.get("threadId"))
                raw_data["message_id_header"] = msg_headers.get("message-id")
                raw_data["reply_to"] = msg_headers.get("reply-to") or msg_headers.get("from") or extracted.organizer
                task_title = extracted.title
                task_description = extracted.description
                task_scheduled_for = extracted.scheduled_for
                task_source = extracted.source
                ext_msg_id = extracted.external_message_id
                existing_cal = {
                    "title": extracted.title,
                    "start_iso": (
                        extracted.scheduled_for.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
                        if extracted.scheduled_for
                        else ""
                    ),
                    "end_iso": raw_data.get("end_time") or "",
                    "location": raw_data.get("location") or "",
                    "description": extracted.description,
                    "attendees": extracted.attendees,
                }
            elif self._include_general_emails:
                email_task = _parse_regular_inbox_email(full_message, msg_id)
                raw_data = dict(email_task["raw_data"])
                task_title = email_task["title"]
                task_description = email_task["description"]
                task_scheduled_for = email_task["scheduled_for"]
                task_source = email_task["source"]
                ext_msg_id = email_task["external_message_id"]
                existing_cal = None
            else:
                ignored_non_invites += 1
                continue

            received_iso = (
                task_scheduled_for.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
                if task_scheduled_for
                else None
            )
            analysis = analyze_email_smart(
                subject=task_title,
                sender=str(raw_data.get("organizer") or msg_headers.get("from") or "Unknown Sender"),
                body=task_description,
                received_at_iso=received_iso,
                reply_to=raw_data.get("reply_to"),
                existing_calendar=existing_cal,
                user_name=user_name,
                user_email=user_email,
            )
            raw_data["ai_analysis"] = analysis
            raw_data.pop("ai_analysis_error", None)
            cal_info = analysis.get("calendar_event") or {}
            if analysis.get("requires_calendar") and cal_info.get("start_iso"):
                parsed_start = _parse_iso_naive_utc(cal_info.get("start_iso"))
                if parsed_start is not None:
                    task_scheduled_for = parsed_start
                if task_source != "calendar":
                    task_source = "calendar"

            db.add(
                Task(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    title=task_title,
                    description=task_description,
                    scheduled_for=task_scheduled_for,
                    source=task_source,
                    status="pending",
                    external_message_id=ext_msg_id,
                    raw_data=raw_data,
                    created_at=now,
                    updated_at=now,
                )
            )
            db.commit()

            existing_ids.add(msg_id)
            created_count += 1

        synced_at = utc_now()
        token_record.last_synced_at = synced_at
        token_record.last_error = None
        token_record.updated_at = synced_at
        db.commit()

        analyzed_existing = self.analyze_unanalyzed_pending_tasks(
            db=db,
            user_id=user_id,
            user_name=user_name,
            user_email=user_email,
            limit=self._max_messages,
        )

        try:
            from app.services.agent_service import apply_agent_policies_for_user

            auto_actions = apply_agent_policies_for_user(db, user_id)
            if auto_actions:
                logger.info(
                    "Joshu Agent auto-executed %d task(s) for user_id=%s",
                    len(auto_actions),
                    user_id,
                )
        except Exception as agent_exc:
            logger.warning("Agent auto-policy evaluation skipped user_id=%s: %s", user_id, agent_exc)

        logger.info(
            "Gmail poll finished user_id=%s query=%r fetched=%d created=%d analyzed_existing=%d skipped=%d ignored=%d",
            user_id,
            used_query,
            fetched_count,
            created_count,
            analyzed_existing,
            skipped_duplicates,
            ignored_non_invites,
        )

        return SyncResult(
            user_id=user_id,
            fetched_messages=fetched_count,
            created_tasks=created_count,
            skipped_duplicates=skipped_duplicates,
            ignored_non_invites=ignored_non_invites,
            synced_at=synced_at.isoformat() + "Z",
            analyzed_tasks=analyzed_existing,
        )

    def analyze_unanalyzed_pending_tasks(
        self,
        *,
        db: DBSession,
        user_id: int,
        user_name: Optional[str] = None,
        user_email: Optional[str] = None,
        limit: int = 25,
    ) -> int:
        """Ensure every pending task has analysis immediately and enrich with Gemini when quota allows."""
        ai_enabled = is_ai_configured()
        pending_tasks: List[Task] = (
            db.query(Task)
            .filter(Task.user_id == user_id, Task.status == "pending")
            .order_by(Task.created_at.desc())
            .all()
        )
        max_to_analyze = max(1, limit)
        analyzed_count = 0
        gemini_quota_exhausted = not ai_enabled

        for task in pending_tasks:
            raw = dict(task.raw_data) if isinstance(task.raw_data, dict) else {}
            if isinstance(raw.get("ai_analysis"), dict):
                continue

            existing_cal = None
            if task.source == "calendar":
                existing_cal = {
                    "title": task.title,
                    "start_iso": (
                        task.scheduled_for.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
                        if task.scheduled_for
                        else ""
                    ),
                    "end_iso": raw.get("end_time") or "",
                    "location": raw.get("location") or "",
                    "description": task.description or "",
                    "attendees": raw.get("attendees") or [],
                }

            received_iso = (
                task.scheduled_for.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
                if task.scheduled_for
                else None
            )

            if not gemini_quota_exhausted and analyzed_count < max_to_analyze:
                try:
                    analysis = analyze_email_with_gemini(
                        subject=task.title or "(No Subject)",
                        sender=str(raw.get("organizer") or "Unknown Sender"),
                        body=task.description or "",
                        received_at_iso=received_iso,
                        reply_to=raw.get("reply_to"),
                        existing_calendar=existing_cal,
                        user_name=user_name,
                        user_email=user_email,
                    )
                    raw["ai_analysis"] = analysis
                    raw.pop("ai_analysis_error", None)
                    cal_info = analysis.get("calendar_event") or {}
                    if analysis.get("requires_calendar") and cal_info.get("start_iso"):
                        parsed_start = _parse_iso_naive_utc(cal_info.get("start_iso"))
                        if parsed_start is not None:
                            task.scheduled_for = parsed_start
                        if task.source != "calendar":
                            task.source = "calendar"
                    task.raw_data = raw
                    flag_modified(task, "raw_data")
                    task.updated_at = utc_now()
                    db.commit()
                    analyzed_count += 1
                    time.sleep(0.15)
                    continue
                except EmailAnalysisError as exc:
                    logger.warning("Gemini analysis fallback for task_id=%s: %s", task.id, exc)
                    if getattr(exc, "status_code", None) in (400, 403, 404, 429):
                        gemini_quota_exhausted = True

            # Guarantee task has complete structured analysis immediately even when Gemini is rate-limited
            fallback_analysis = build_instant_analysis(
                subject=task.title or "(No Subject)",
                sender=str(raw.get("organizer") or "Unknown Sender"),
                body=task.description or "",
                received_at_iso=received_iso,
                reply_to=raw.get("reply_to"),
                existing_calendar=existing_cal,
                user_name=user_name,
                user_email=user_email,
                needs_deep_ai=False,
            )
            raw["ai_analysis"] = fallback_analysis
            raw.pop("ai_analysis_error", None)
            cal_info = fallback_analysis.get("calendar_event") or {}
            if fallback_analysis.get("requires_calendar") and cal_info.get("start_iso"):
                parsed_start = _parse_iso_naive_utc(cal_info.get("start_iso"))
                if parsed_start is not None:
                    task.scheduled_for = parsed_start
                if task.source != "calendar":
                    task.source = "calendar"
            task.raw_data = raw
            flag_modified(task, "raw_data")
            task.updated_at = utc_now()
            db.commit()
            analyzed_count += 1

        return analyzed_count

    def has_unanalyzed_pending_tasks(self, db: DBSession) -> bool:
        """Return True if any connected user still has pending tasks missing analysis."""
        pending_tasks = (
            db.query(Task)
            .join(GoogleOAuthToken, GoogleOAuthToken.user_id == Task.user_id)
            .filter(
                Task.status == "pending",
                GoogleOAuthToken.needs_reconnect.is_(False),
            )
            .limit(100)
            .all()
        )
        for task in pending_tasks:
            raw = task.raw_data if isinstance(task.raw_data, dict) else {}
            if not isinstance(raw.get("ai_analysis"), dict):
                return True
        return False

    def poll_all_active_users(self, db: DBSession) -> Dict[str, Any]:
        """Poll Gmail and run AI analysis for every connected user in the background, even when logged out."""
        connected_user_ids = [
            row[0]
            for row in db.query(GoogleOAuthToken.user_id)
            .filter(GoogleOAuthToken.needs_reconnect.is_(False))
            .distinct()
            .all()
        ]

        summary: Dict[str, Any] = {
            "polled_users": 0,
            "created_tasks": 0,
            "analyzed_tasks": 0,
            "errors": 0,
            "has_more_to_analyze": False,
        }

        for uid in connected_user_ids:
            try:
                result = self.poll_user_inbox(db, uid)
                summary["polled_users"] += 1
                summary["created_tasks"] += result.created_tasks
                summary["analyzed_tasks"] += result.analyzed_tasks
            except GmailPollingError as exc:
                summary["errors"] += 1
                logger.warning("Gmail poll skipped for user_id=%s: %s", uid, exc)
            except Exception:
                summary["errors"] += 1
                logger.exception("Unexpected error during Gmail poll for user_id=%s", uid)

        summary["has_more_to_analyze"] = self.has_unanalyzed_pending_tasks(db)
        return summary


class GmailPollingScheduler:
    """Asyncio background loop that continuously syncs Gmail and analyzes emails even when signed out."""

    def __init__(
        self,
        service: Optional[GmailPollingService] = None,
        session_factory: Callable[[], DBSession] = SessionLocal,
        interval_minutes: Optional[int] = None,
    ) -> None:
        self._service = service or GmailPollingService()
        self._session_factory = session_factory
        self._interval_minutes = interval_minutes or get_poll_interval_minutes()
        self._task: Optional[asyncio.Task[None]] = None
        self._stop_event = asyncio.Event()

    @property
    def interval_minutes(self) -> int:
        return self._interval_minutes

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def _run_cycle_sync(self) -> Dict[str, Any]:
        db = self._session_factory()
        try:
            return self._service.poll_all_active_users(db)
        finally:
            db.close()

    def _get_effective_poll_seconds(self) -> int:
        raw_sec = (os.getenv("GMAIL_POLL_INTERVAL_SECONDS") or "").strip()
        if raw_sec:
            try:
                return max(15, int(raw_sec))
            except ValueError:
                pass
        # Cap default wait at 60s so background syncing & AI review generation stays snappy on localhost.
        return min(max(30, self._interval_minutes * 60), DEFAULT_POLL_INTERVAL_SECONDS)

    async def _loop(self) -> None:
        base_interval_seconds = self._get_effective_poll_seconds()
        logger.info("Continuous background Gmail + AI scheduler started (interval=%ds)", base_interval_seconds)
        # Run first cycle immediately (1s after startup) so reviews are ready before the user even opens the app.
        next_wait_seconds = 1
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=next_wait_seconds)
                break
            except asyncio.TimeoutError:
                next_wait_seconds = base_interval_seconds
                try:
                    summary = await asyncio.to_thread(self._run_cycle_sync)
                    logger.info(
                        "Background sync cycle complete: users=%s created=%s analyzed=%s more=%s errors=%s",
                        summary["polled_users"],
                        summary["created_tasks"],
                        summary.get("analyzed_tasks", 0),
                        summary.get("has_more_to_analyze", False),
                        summary["errors"],
                    )
                    if summary.get("has_more_to_analyze"):
                        next_wait_seconds = BACKGROUND_RETRY_SECONDS
                except Exception:
                    logger.exception("Gmail polling cycle encountered an unexpected error")

    def start(self) -> None:
        if not is_polling_enabled() or self.is_running:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._loop(), name="joshu-gmail-poller")

    async def stop(self) -> None:
        if not self.is_running:
            return
        self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Gmail polling scheduler stopped")


gmail_polling_service = GmailPollingService()
gmail_polling_scheduler = GmailPollingScheduler(service=gmail_polling_service)
