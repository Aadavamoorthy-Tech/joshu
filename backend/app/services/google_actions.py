"""Real Google Gmail & Google Calendar execution actions for approved Chief of Staff tasks."""

from __future__ import annotations

import base64
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import parseaddr
from typing import Any, Callable, Dict, List, Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build as build_google_service
from googleapiclient.errors import HttpError
from sqlalchemy.orm import Session as DBSession

from app.models.task import GoogleOAuthToken
from app.services.gmail_poller import (
    GmailApiError,
    GmailScopeMissingError,
    GoogleTokenExpiredError,
    _build_google_credentials,
)

logger = logging.getLogger("joshu.google_actions")

DEFAULT_PROCESSED_FOLDER = "Joshu/Processed"
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


class GoogleActionError(RuntimeError):
    """Base error raised when executing an approved Gmail or Google Calendar action."""


class ScopeUpgradeRequiredError(GoogleActionError):
    """Raised when the user's Google OAuth token lacks required send/modify/calendar scopes."""


def get_processed_folder_name() -> str:
    return (os.getenv("GMAIL_PROCESSED_LABEL") or DEFAULT_PROCESSED_FOLDER).strip() or DEFAULT_PROCESSED_FOLDER


def _default_gmail_factory(creds: Credentials) -> Any:
    return build_google_service("gmail", "v1", credentials=creds, cache_discovery=False)


def _default_calendar_factory(creds: Credentials) -> Any:
    return build_google_service("calendar", "v3", credentials=creds, cache_discovery=False)


def _sanitize_header_value(value: str, field_name: str, max_len: int = 300) -> str:
    cleaned = str(value or "").strip()
    if "\r" in cleaned or "\n" in cleaned:
        raise GoogleActionError(f"Invalid header characters in {field_name}.")
    return cleaned[:max_len]


def _validate_recipient_email(raw: str) -> str:
    _, addr = parseaddr(str(raw or "").strip())
    addr = addr.strip().lower()
    if not addr or not _EMAIL_RE.match(addr):
        raise GoogleActionError("A valid recipient email address is required to send a reply.")
    return addr


def _parse_iso_utc(raw: str) -> datetime:
    text = str(raw or "").strip()
    if not text:
        raise GoogleActionError("A valid meeting start date and time is required for Google Calendar.")
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt
    except ValueError as exc:
        raise GoogleActionError(f"Invalid meeting date/time format: {text}") from exc


def _format_rfc3339(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class GoogleActionsService:
    """Executes real Gmail replies, Google Calendar event creation, and Inbox archiving/read updates."""

    def __init__(
        self,
        gmail_service_factory: Callable[[Credentials], Any] = _default_gmail_factory,
        calendar_service_factory: Callable[[Credentials], Any] = _default_calendar_factory,
    ) -> None:
        self._gmail_service_factory = gmail_service_factory
        self._calendar_service_factory = calendar_service_factory

    def get_token_record(self, db: DBSession, user_id: int) -> Optional[GoogleOAuthToken]:
        return (
            db.query(GoogleOAuthToken)
            .filter(GoogleOAuthToken.user_id == user_id)
            .first()
        )

    def _get_credentials_or_raise(
        self,
        db: DBSession,
        user_id: int,
        *,
        require_send: bool = False,
        require_modify: bool = False,
        require_calendar: bool = False,
    ) -> Credentials:
        token_record = self.get_token_record(db, user_id)
        if token_record is None:
            raise GoogleTokenExpiredError(
                "No connected Google account found. Please sign in with Google again."
            )

        missing: List[str] = []
        if require_send and not token_record.has_gmail_send():
            missing.append("Gmail Send")
        if require_modify and not token_record.has_gmail_modify():
            missing.append("Gmail Modify (mark read & move folder)")
        if require_calendar and not token_record.has_calendar_events():
            missing.append("Google Calendar")

        if missing:
            raise ScopeUpgradeRequiredError(
                f"Additional Google permissions are required ({', '.join(missing)}). "
                "Click Logout and Sign In with Google once to grant these permissions."
            )

        return _build_google_credentials(token_record, db)

    def send_gmail_reply(
        self,
        db: DBSession,
        user_id: int,
        *,
        to_email: str,
        subject: str,
        body: str,
        thread_id: Optional[str] = None,
        in_reply_to: Optional[str] = None,
        references: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send an approved email reply via Gmail API, preserving thread headers."""
        recipient = _validate_recipient_email(to_email)
        clean_subject = _sanitize_header_value(subject or "Re: Follow-up", "subject", 250)
        clean_body = str(body or "").strip()
        if not clean_body:
            raise GoogleActionError("Reply message body cannot be empty.")

        creds = self._get_credentials_or_raise(db, user_id, require_send=True)

        msg = EmailMessage()
        msg["To"] = recipient
        msg["Subject"] = clean_subject
        if in_reply_to:
            clean_ref = _sanitize_header_value(in_reply_to, "In-Reply-To", 250)
            if clean_ref:
                msg["In-Reply-To"] = clean_ref
                msg["References"] = _sanitize_header_value(references or clean_ref, "References", 500)
        msg.set_content(clean_body)

        encoded_raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
        send_body: Dict[str, Any] = {"raw": encoded_raw}
        if thread_id:
            send_body["threadId"] = str(thread_id).strip()

        try:
            gmail = self._gmail_service_factory(creds)
            sent = gmail.users().messages().send(userId="me", body=send_body).execute()
        except HttpError as exc:
            status = getattr(exc.resp, "status", None)
            if status == 403:
                raise ScopeUpgradeRequiredError(
                    "Gmail send permission was denied (403). Sign out and sign in with Google again to grant gmail.send permission."
                ) from exc
            if status == 401:
                raise GoogleTokenExpiredError(
                    "Google session expired while sending email. Please sign in again."
                ) from exc
            raise GoogleActionError(f"Failed to send Gmail reply (HTTP {status}).") from exc
        except Exception as exc:
            raise GoogleActionError("Network error while sending Gmail reply.") from exc

        logger.info("Sent Gmail reply user_id=%s to=%s sent_id=%s", user_id, recipient, sent.get("id"))
        return {
            "sent": True,
            "message_id": sent.get("id"),
            "thread_id": sent.get("threadId") or thread_id,
            "to": recipient,
            "subject": clean_subject,
            "sent_at": _format_rfc3339(datetime.now(timezone.utc)),
        }

    def create_calendar_event(
        self,
        db: DBSession,
        user_id: int,
        *,
        title: str,
        start_iso: str,
        end_iso: Optional[str] = None,
        description: str = "",
        location: str = "",
        attendees: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Create a real Google Calendar event on the user's primary calendar."""
        clean_title = _sanitize_header_value(title or "Scheduled Meeting", "title", 250)
        start_dt = _parse_iso_utc(start_iso)
        if end_iso:
            try:
                end_dt = _parse_iso_utc(end_iso)
                if end_dt <= start_dt:
                    end_dt = start_dt + timedelta(hours=1)
            except GoogleActionError:
                end_dt = start_dt + timedelta(hours=1)
        else:
            end_dt = start_dt + timedelta(hours=1)

        creds = self._get_credentials_or_raise(db, user_id, require_calendar=True)

        valid_attendees = []
        for raw_email in attendees or []:
            _, addr = parseaddr(str(raw_email or "").strip())
            addr = addr.strip().lower()
            if addr and _EMAIL_RE.match(addr):
                valid_attendees.append({"email": addr})

        event_body: Dict[str, Any] = {
            "summary": clean_title,
            "description": str(description or "").strip()[:3000],
            "start": {"dateTime": _format_rfc3339(start_dt), "timeZone": "UTC"},
            "end": {"dateTime": _format_rfc3339(end_dt), "timeZone": "UTC"},
        }
        if location and str(location).strip():
            event_body["location"] = _sanitize_header_value(str(location), "location", 300)
        if valid_attendees:
            event_body["attendees"] = valid_attendees

        try:
            calendar = self._calendar_service_factory(creds)
            created = (
                calendar.events()
                .insert(calendarId="primary", body=event_body, sendUpdates="none")
                .execute()
            )
        except HttpError as exc:
            status = getattr(exc.resp, "status", None)
            if status == 403:
                raise ScopeUpgradeRequiredError(
                    "Google Calendar API access was denied (403). Enable the Google Calendar API in Google Cloud Console and sign in again to grant calendar.events permission."
                ) from exc
            if status == 401:
                raise GoogleTokenExpiredError(
                    "Google session expired while creating calendar event. Please sign in again."
                ) from exc
            raise GoogleActionError(f"Failed to create Google Calendar event (HTTP {status}).") from exc
        except Exception as exc:
            raise GoogleActionError("Network error while creating Google Calendar event.") from exc

        logger.info("Created Google Calendar event user_id=%s event_id=%s", user_id, created.get("id"))
        return {
            "created": True,
            "event_id": created.get("id"),
            "html_link": created.get("htmlLink"),
            "summary": created.get("summary") or clean_title,
            "start": _format_rfc3339(start_dt),
            "end": _format_rfc3339(end_dt),
            "created_at": _format_rfc3339(datetime.now(timezone.utc)),
        }

    def _ensure_label_id(self, gmail: Any, label_name: str) -> str:
        labels_resp = gmail.users().labels().list(userId="me").execute()
        for lbl in labels_resp.get("labels") or []:
            if str(lbl.get("name") or "").strip().lower() == label_name.lower():
                return str(lbl["id"])

        created = (
            gmail.users()
            .labels()
            .create(
                userId="me",
                body={
                    "name": label_name,
                    "labelListVisibility": "labelShow",
                    "messageListVisibility": "show",
                },
            )
            .execute()
        )
        return str(created["id"])

    def mark_read_and_move_to_folder(
        self,
        db: DBSession,
        user_id: int,
        *,
        message_id: str,
        folder_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Mark the Gmail message as read and move it out of INBOX into the processed folder/label."""
        clean_msg_id = str(message_id or "").strip()
        if not clean_msg_id:
            return {"processed": False, "reason": "No Gmail message ID associated with task"}

        target_folder = (folder_name or get_processed_folder_name()).strip() or DEFAULT_PROCESSED_FOLDER
        creds = self._get_credentials_or_raise(db, user_id, require_modify=True)

        try:
            gmail = self._gmail_service_factory(creds)
            label_id = self._ensure_label_id(gmail, target_folder)
            gmail.users().messages().modify(
                userId="me",
                id=clean_msg_id,
                body={
                    "addLabelIds": [label_id],
                    "removeLabelIds": ["UNREAD", "INBOX"],
                },
            ).execute()
        except HttpError as exc:
            status = getattr(exc.resp, "status", None)
            if status == 403:
                raise ScopeUpgradeRequiredError(
                    "Gmail modify permission was denied (403). Sign out and sign in with Google again to allow marking emails read and moving them to a folder."
                ) from exc
            if status == 401:
                raise GoogleTokenExpiredError(
                    "Google session expired while organizing Gmail inbox. Please sign in again."
                ) from exc
            if status == 404:
                return {
                    "processed": False,
                    "message_id": clean_msg_id,
                    "folder": target_folder,
                    "reason": "Message no longer exists in Gmail",
                }
            raise GoogleActionError(f"Failed to mark read and move Gmail message (HTTP {status}).") from exc
        except Exception as exc:
            raise GoogleActionError("Network error while updating Gmail message labels.") from exc

        logger.info(
            "Marked Gmail message read & moved user_id=%s msg_id=%s folder=%s",
            user_id,
            clean_msg_id,
            target_folder,
        )
        return {
            "processed": True,
            "message_id": clean_msg_id,
            "marked_read": True,
            "removed_from_inbox": True,
            "folder": target_folder,
            "label_id": label_id,
            "processed_at": _format_rfc3339(datetime.now(timezone.utc)),
        }


google_actions_service = GoogleActionsService()
