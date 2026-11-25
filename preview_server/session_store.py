"""Thread-safe session management, per-account task isolation, and real background polling.

Zero demo or fake data: every session is backed by either:
- Real Google OAuth 2.0 (`gmail.readonly` via Gmail REST API), or
- Real universal IMAPS over TLS 993 (`imaplib.IMAP4_SSL`).
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from preview_server.agent_engine import default_agent_policy
from preview_server.google_oauth_service import (
    GoogleTokenExpiredError,
    build_google_authorization_url,
    exchange_google_authorization_code,
    fetch_gmail_api_inbox_messages,
    fetch_google_userinfo,
    refresh_google_access_token,
)
from preview_server.imap_service import (
    ImapValidationError,
    detect_imap_provider,
    fetch_imap_inbox_messages,
    normalize_email,
    validate_imap_target,
)

SESSION_TTL_HOURS = 8
OAUTH_STATE_TTL_MINUTES = 10
EXCHANGE_CODE_TTL_SECONDS = 60
MIN_POLL_MINUTES = 1
MAX_POLL_MINUTES = 60


def _iso_utc(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    else:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class PendingOAuthState:
    state: str
    redirect_uri: str
    origin: str
    poll_interval_minutes: int
    expires_at: datetime


@dataclass
class PendingExchangeCode:
    code: str
    session_token: str
    initial_synced: int
    expires_at: datetime


@dataclass
class MailboxSession:
    token: str
    email: str
    display_name: str
    picture_url: Optional[str]
    provider: str
    connection_label: str
    mode: str  # "google_oauth" | "imap"
    created_at: datetime
    expires_at: datetime
    poll_interval_minutes: int = 15
    auto_poll_enabled: bool = True
    last_polled_at: Optional[datetime] = None
    next_poll_at: Optional[datetime] = None
    last_poll_error: Optional[str] = None
    poll_count: int = 0

    # In-memory credentials strictly cleared on sign-out or expiry (never serialized or logged).
    _imap_host: Optional[str] = field(default=None, repr=False)
    _imap_port: int = field(default=993, repr=False)
    _imap_password: Optional[str] = field(default=None, repr=False)
    _oauth_access_token: Optional[str] = field(default=None, repr=False)
    _oauth_refresh_token: Optional[str] = field(default=None, repr=False)
    _oauth_token_expiry: Optional[datetime] = field(default=None, repr=False)
    _request_origin: str = field(default="http://localhost:3000", repr=False)

    tasks: List[Dict[str, Any]] = field(default_factory=list)
    agent_policy: Dict[str, Any] = field(default_factory=default_agent_policy)
    agent_messages: List[Dict[str, Any]] = field(default_factory=list)
    agent_connected_services: List[str] = field(default_factory=lambda: ["gmail", "calendar"])
    stop_event: threading.Event = field(default_factory=threading.Event, repr=False)
    poller_thread: Optional[threading.Thread] = field(default=None, repr=False)

    def to_public_dict(self) -> Dict[str, Any]:
        return {
            "email": self.email,
            "display_name": self.display_name,
            "picture_url": self.picture_url,
            "provider": self.provider,
            "connection_label": self.connection_label,
            "mode": self.mode,
            "poll_interval_minutes": self.poll_interval_minutes,
            "auto_poll_enabled": self.auto_poll_enabled,
            "last_polled_at": _iso_utc(self.last_polled_at),
            "next_poll_at": _iso_utc(self.next_poll_at) if self.auto_poll_enabled else None,
            "last_poll_error": self.last_poll_error,
            "poll_count": self.poll_count,
            "expires_at": _iso_utc(self.expires_at),
        }


class SessionManager:
    """Manages active authenticated mailbox sessions, account isolation, and live polling."""

    def __init__(
        self,
        imap_fetcher: Callable[..., List[Dict[str, Any]]] = fetch_imap_inbox_messages,
        gmail_fetcher: Callable[..., List[Dict[str, Any]]] = fetch_gmail_api_inbox_messages,
        enable_background_threads: bool = True,
    ) -> None:
        self._sessions: Dict[str, MailboxSession] = {}
        self._oauth_states: Dict[str, PendingOAuthState] = {}
        self._exchange_codes: Dict[str, PendingExchangeCode] = {}
        self._lock = threading.RLock()
        self._imap_fetcher = imap_fetcher
        self._gmail_fetcher = gmail_fetcher
        self._enable_background_threads = enable_background_threads

    @staticmethod
    def _clamp_poll_interval(minutes: Any) -> int:
        try:
            val = int(minutes)
        except (TypeError, ValueError):
            val = 15
        return max(MIN_POLL_MINUTES, min(MAX_POLL_MINUTES, val))

    def _prune_ephemeral_locked(self) -> None:
        now = datetime.now(timezone.utc)
        for key in [k for k, v in self._oauth_states.items() if v.expires_at <= now]:
            self._oauth_states.pop(key, None)
        for key in [k for k, v in self._exchange_codes.items() if v.expires_at <= now]:
            self._exchange_codes.pop(key, None)

    def _merge_polled_tasks(
        self,
        session: MailboxSession,
        polled_items: List[Dict[str, Any]],
    ) -> int:
        """Merge newly polled items without duplicating existing messages or overwriting decisions."""
        existing_ids = {t.get("external_message_id") for t in session.tasks if t.get("external_message_id")}
        new_items: List[Dict[str, Any]] = []
        for item in polled_items:
            ext_id = item.get("external_message_id")
            if ext_id and ext_id in existing_ids:
                continue
            item["account_email"] = session.email
            new_items.append(item)
            if ext_id:
                existing_ids.add(ext_id)

        if new_items:
            session.tasks = new_items + session.tasks
        return len(new_items)

    def _fetch_for_session(self, session: MailboxSession) -> List[Dict[str, Any]]:
        """Execute a live poll against the signed-in mailbox (Google Gmail API or IMAP)."""
        if session.mode == "imap":
            if not session._imap_host or not session._imap_password:
                raise ImapValidationError("IMAP session credentials are no longer active. Please sign in again.")
            return self._imap_fetcher(
                email_address=session.email,
                password=session._imap_password,
                imap_host=session._imap_host,
                imap_port=session._imap_port,
                max_messages=20,
            )

        # Google OAuth mode
        if not session._oauth_access_token:
            raise GoogleTokenExpiredError("Google session token missing. Please sign in again.")

        now = datetime.now(timezone.utc)
        needs_refresh = (
            session._oauth_token_expiry is not None
            and session._oauth_token_expiry <= now + timedelta(minutes=2)
        )
        if needs_refresh and session._oauth_refresh_token:
            refreshed = refresh_google_access_token(
                refresh_token=session._oauth_refresh_token,
                request_origin=session._request_origin,
            )
            session._oauth_access_token = refreshed["access_token"]
            session._oauth_token_expiry = refreshed["token_expiry"]

        try:
            return self._gmail_fetcher(
                access_token=session._oauth_access_token,
                account_email=session.email,
                max_messages=20,
            )
        except GoogleTokenExpiredError:
            if not session._oauth_refresh_token:
                raise
            refreshed = refresh_google_access_token(
                refresh_token=session._oauth_refresh_token,
                request_origin=session._request_origin,
            )
            session._oauth_access_token = refreshed["access_token"]
            session._oauth_token_expiry = refreshed["token_expiry"]
            return self._gmail_fetcher(
                access_token=session._oauth_access_token,
                account_email=session.email,
                max_messages=20,
            )

    def _start_poller_thread(self, session: MailboxSession) -> None:
        if not self._enable_background_threads:
            return

        def _worker() -> None:
            while not session.stop_event.is_set():
                interval_sec = max(60, session.poll_interval_minutes * 60)
                if session.stop_event.wait(timeout=interval_sec):
                    break

                with self._lock:
                    if session.token not in self._sessions:
                        break
                    if datetime.now(timezone.utc) >= session.expires_at:
                        self._cleanup_session_locked(session.token)
                        break
                    if not session.auto_poll_enabled:
                        continue

                try:
                    fetched = self._fetch_for_session(session)
                    now = datetime.now(timezone.utc)
                    with self._lock:
                        if session.token in self._sessions:
                            self._merge_polled_tasks(session, fetched)
                            session.last_polled_at = now
                            session.next_poll_at = now + timedelta(minutes=session.poll_interval_minutes)
                            session.last_poll_error = None
                            session.poll_count += 1
                except Exception as exc:
                    now = datetime.now(timezone.utc)
                    with self._lock:
                        if session.token in self._sessions:
                            session.last_poll_error = str(exc)
                            session.next_poll_at = now + timedelta(minutes=session.poll_interval_minutes)

        thread = threading.Thread(target=_worker, name=f"joshu-poll-{session.email}", daemon=True)
        session.poller_thread = thread
        thread.start()

    def _cleanup_session_locked(self, token: str) -> None:
        session = self._sessions.pop(token, None)
        if session is not None:
            session.stop_event.set()
            session._imap_password = None
            session._oauth_access_token = None
            session._oauth_refresh_token = None
            session.tasks.clear()

    # ── Google OAuth 2.0 Flow ────────────────────────────────────────────────

    def start_google_oauth(
        self,
        request_origin: str,
        poll_interval_minutes: int = 15,
        requested_redirect_uri: Optional[str] = None,
    ) -> Tuple[str, str]:
        """Generate a single-use CSRF state and Google account-selection OAuth URL."""
        state = secrets.token_urlsafe(32)
        auth_url, redirect_uri = build_google_authorization_url(
            request_origin=request_origin,
            state=state,
            requested_redirect_uri=requested_redirect_uri,
        )
        interval = self._clamp_poll_interval(poll_interval_minutes)
        now = datetime.now(timezone.utc)
        with self._lock:
            self._prune_ephemeral_locked()
            self._oauth_states[state] = PendingOAuthState(
                state=state,
                redirect_uri=redirect_uri,
                origin=request_origin.rstrip("/"),
                poll_interval_minutes=interval,
                expires_at=now + timedelta(minutes=OAUTH_STATE_TTL_MINUTES),
            )
        return auth_url, redirect_uri

    def _establish_google_session(
        self,
        code: str,
        state: str,
    ) -> Tuple[str, MailboxSession, int, str]:
        """Consume CSRF state, exchange auth code, poll that signed-in Gmail inbox, and start background polling."""
        now = datetime.now(timezone.utc)
        with self._lock:
            self._prune_ephemeral_locked()
            pending = self._oauth_states.pop(state.strip(), None)

        if pending is None or pending.expires_at <= now:
            raise ValueError("Sign-in state is invalid, expired, or already used. Please try signing in again.")

        token_bundle = exchange_google_authorization_code(
            code=code,
            redirect_uri=pending.redirect_uri,
            request_origin=pending.origin,
        )
        profile = fetch_google_userinfo(token_bundle["access_token"])
        account_email = profile["email"]

        # Poll the newly signed-in Google account's inbox immediately.
        initial_tasks = self._gmail_fetcher(
            access_token=token_bundle["access_token"],
            account_email=account_email,
            max_messages=20,
        )

        session_token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        session = MailboxSession(
            token=session_token,
            email=account_email,
            display_name=profile["name"],
            picture_url=profile["picture_url"],
            provider="Google Gmail API",
            connection_label="Gmail API · gmail.readonly",
            mode="google_oauth",
            created_at=now,
            expires_at=now + timedelta(hours=SESSION_TTL_HOURS),
            poll_interval_minutes=pending.poll_interval_minutes,
            auto_poll_enabled=True,
            last_polled_at=now,
            next_poll_at=now + timedelta(minutes=pending.poll_interval_minutes),
            last_poll_error=None,
            poll_count=1,
            _oauth_access_token=token_bundle["access_token"],
            _oauth_refresh_token=token_bundle["refresh_token"],
            _oauth_token_expiry=token_bundle["token_expiry"],
            _request_origin=pending.origin,
            tasks=[],
        )
        created_count = self._merge_polled_tasks(session, initial_tasks)

        with self._lock:
            self._sessions[session_token] = session
        self._start_poller_thread(session)
        return session_token, session, created_count, pending.origin

    def complete_google_oauth_callback(
        self,
        code: str,
        state: str,
    ) -> Tuple[str, str]:
        """Complete server-redirect OAuth callback and issue a single-use short-lived exchange code."""
        session_token, _, created_count, origin = self._establish_google_session(code=code, state=state)
        exchange_code = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        with self._lock:
            self._exchange_codes[exchange_code] = PendingExchangeCode(
                code=exchange_code,
                session_token=session_token,
                initial_synced=created_count,
                expires_at=now + timedelta(seconds=EXCHANGE_CODE_TTL_SECONDS),
            )
        return exchange_code, origin

    def complete_google_oauth_direct(
        self,
        code: str,
        state: str,
    ) -> Tuple[str, MailboxSession, int]:
        """Complete XHR OAuth callback directly and return the new session token and profile."""
        session_token, session, created_count, _ = self._establish_google_session(code=code, state=state)
        return session_token, session, created_count

    def redeem_exchange_code(self, exchange_code: str) -> Optional[Tuple[str, MailboxSession, int]]:
        """Redeem a short-lived exchange code for the active session token."""
        now = datetime.now(timezone.utc)
        with self._lock:
            self._prune_ephemeral_locked()
            clean_code = (exchange_code or "").strip()
            entry = self._exchange_codes.get(clean_code)
            if entry is None or entry.expires_at <= now:
                self._exchange_codes.pop(clean_code, None)
                return None
            # Keep valid for a brief 15-second grace window so both the OAuth tab and an embedded preview iframe can redeem it
            grace_expiry = now + timedelta(seconds=15)
            if entry.expires_at > grace_expiry:
                entry.expires_at = grace_expiry
            session = self._sessions.get(entry.session_token)
            if session is None:
                self._exchange_codes.pop(clean_code, None)
                return None
            return entry.session_token, session, entry.initial_synced

    # ── Universal IMAP Sign-In Flow ──────────────────────────────────────────

    def sign_in_imap(
        self,
        email_address: str,
        password: str,
        imap_host: Optional[str] = None,
        imap_port: int = 993,
        poll_interval_minutes: int = 15,
    ) -> Tuple[str, MailboxSession, int]:
        """Authenticate against any user-supplied IMAPS mailbox, run initial poll, and start background polling."""
        clean_email = normalize_email(email_address)
        if not password or not password.strip():
            raise ImapValidationError("Password or App Password is required.")

        detected = detect_imap_provider(clean_email)
        chosen_host = (imap_host or "").strip() or detected.host
        if not chosen_host:
            raise ImapValidationError("Please enter your IMAP server hostname in Custom IMAP Server settings.")

        validated_host, validated_port = validate_imap_target(chosen_host, imap_port)
        interval = self._clamp_poll_interval(poll_interval_minutes)

        initial_tasks = self._imap_fetcher(
            email_address=clean_email,
            password=password,
            imap_host=validated_host,
            imap_port=validated_port,
            max_messages=20,
        )

        now = datetime.now(timezone.utc)
        token = secrets.token_urlsafe(32)
        provider_label = detected.provider if validated_host == detected.host else "Custom IMAP"
        session = MailboxSession(
            token=token,
            email=clean_email,
            display_name=clean_email.split("@", 1)[0],
            picture_url=None,
            provider=provider_label,
            connection_label=f"{validated_host}:{validated_port} · TLS",
            mode="imap",
            created_at=now,
            expires_at=now + timedelta(hours=SESSION_TTL_HOURS),
            poll_interval_minutes=interval,
            auto_poll_enabled=True,
            last_polled_at=now,
            next_poll_at=now + timedelta(minutes=interval),
            last_poll_error=None,
            poll_count=1,
            _imap_host=validated_host,
            _imap_port=validated_port,
            _imap_password=password,
            tasks=[],
        )
        created_count = self._merge_polled_tasks(session, initial_tasks)

        with self._lock:
            self._sessions[token] = session
        self._start_poller_thread(session)

        return token, session, created_count

    # ── Session, Tasks, Polling & Approval Operations ────────────────────────

    def get_session(self, token: Optional[str]) -> Optional[MailboxSession]:
        if not token:
            return None
        with self._lock:
            session = self._sessions.get(token)
            if session is None:
                return None
            if datetime.now(timezone.utc) >= session.expires_at:
                self._cleanup_session_locked(token)
                return None
            return session

    def sign_out(self, token: Optional[str]) -> bool:
        if not token:
            return False
        with self._lock:
            existed = token in self._sessions
            self._cleanup_session_locked(token)
            return existed

    def list_tasks(
        self,
        token: str,
        status_filter: str = "all",
        source_filter: str = "all",
    ) -> Optional[Dict[str, Any]]:
        with self._lock:
            session = self.get_session(token)
            if session is None:
                return None

            counts = {
                "all": len(session.tasks),
                "pending": 0,
                "approved": 0,
                "rejected": 0,
                "calendar": 0,
                "email": 0,
            }
            for task in session.tasks:
                self._ensure_task_ai_analysis(task, session.display_name, session.email)
                st = task.get("status")
                if st in counts:
                    counts[st] += 1
                src = task.get("source")
                if src in counts:
                    counts[src] += 1

            items = list(session.tasks)
            if status_filter and status_filter != "all":
                items = [t for t in items if t.get("status") == status_filter]
            if source_filter and source_filter != "all":
                items = [t for t in items if t.get("source") == source_filter]

            return {
                "tasks": items,
                "total": len(items),
                "counts": counts,
                "session": session.to_public_dict(),
            }

    def _ensure_task_ai_analysis(
        self,
        task: Dict[str, Any],
        user_name: str,
        user_email: str,
    ) -> None:
        if isinstance(task.get("ai_analysis"), dict) and task["ai_analysis"].get("summary"):
            return
        subject = str(task.get("title") or "(No Subject)").strip()
        sender = str(task.get("organizer") or "Sender").strip()
        body = str(task.get("description") or "").strip()
        is_cal = task.get("source") == "calendar" or bool(task.get("is_meeting_invite"))
        existing_cal = (
            {
                "title": subject,
                "start_iso": task.get("scheduled_for") or "",
                "end_iso": "",
                "location": "",
                "description": body,
                "attendees": task.get("attendees") or [],
            }
            if is_cal
            else None
        )
        try:
            import sys
            from pathlib import Path

            backend_dir = str(Path(__file__).resolve().parent.parent / "backend")
            if backend_dir not in sys.path:
                sys.path.insert(0, backend_dir)
            from app.services.email_analyzer import build_instant_analysis

            ai = build_instant_analysis(
                subject=subject,
                sender=sender,
                body=body,
                received_at_iso=task.get("scheduled_for"),
                reply_to=sender,
                existing_calendar=existing_cal,
                user_name=user_name,
                user_email=user_email,
                needs_deep_ai=False,
            )
            task["ai_analysis"] = ai
            task["action_category"] = ai.get("category") or ("meeting_invite" if is_cal else "informational")
            task["recommended_action"] = ai.get("recommended_action")
        except Exception:
            sender_short = sender.split("<")[0].strip().strip('"') or sender
            if is_cal:
                summary = (
                    f"{sender_short} shared a meeting or calendar invitation for \"{subject}\" "
                    f"ready to be added to your Google Calendar."
                )
                category = "meeting_invite"
                rec = f"Add '{subject}' to Google Calendar and archive email?"
            else:
                summary = (
                    f"Email from {sender_short} regarding \"{subject}\". "
                    f"Click this card to inspect the full message content."
                )
                category = "informational"
                rec = f"Mark this email from {sender_short} as read and move to processed folder?"
            task["ai_analysis"] = {
                "category": category,
                "summary": summary,
                "recommended_action": rec,
                "requires_reply": False,
                "requires_payment": False,
                "requires_calendar": is_cal,
                "requires_rsvp": False,
            }
            task["action_category"] = category
            task["recommended_action"] = rec

    def sync_now(self, token: str) -> Tuple[Optional[MailboxSession], int]:
        """Trigger an immediate real poll for the signed-in mailbox."""
        with self._lock:
            session = self.get_session(token)
            if session is None:
                return None, 0

        fetched = self._fetch_for_session(session)

        now_utc = datetime.now(timezone.utc)
        with self._lock:
            live_session = self.get_session(token)
            if live_session is None:
                return None, 0
            created = self._merge_polled_tasks(live_session, fetched)
            live_session.last_polled_at = now_utc
            live_session.next_poll_at = now_utc + timedelta(minutes=live_session.poll_interval_minutes)
            live_session.last_poll_error = None
            live_session.poll_count += 1
            return live_session, created

    def update_polling_config(
        self,
        token: str,
        auto_poll_enabled: Optional[bool] = None,
        poll_interval_minutes: Optional[int] = None,
    ) -> Optional[MailboxSession]:
        with self._lock:
            session = self.get_session(token)
            if session is None:
                return None
            if auto_poll_enabled is not None:
                session.auto_poll_enabled = bool(auto_poll_enabled)
            if poll_interval_minutes is not None:
                session.poll_interval_minutes = self._clamp_poll_interval(poll_interval_minutes)
            now = datetime.now(timezone.utc)
            session.next_poll_at = (
                now + timedelta(minutes=session.poll_interval_minutes)
                if session.auto_poll_enabled
                else None
            )
            return session

    def decide_task(
        self,
        token: str,
        task_id: str,
        action: str,
        reason: Optional[str] = None,
    ) -> Tuple[Optional[Dict[str, Any]], str]:
        """Approve or reject a task belonging strictly to the authenticated session."""
        with self._lock:
            session = self.get_session(token)
            if session is None:
                return None, "unauthorized"

            task = next(
                (t for t in session.tasks if t["id"] == task_id and t.get("account_email") == session.email),
                None,
            )
            if task is None:
                return None, "not_found"

            now_iso = _iso_utc(datetime.now(timezone.utc))
            if action == "approve":
                if task["status"] != "approved":
                    task["status"] = "approved"
                    task["approved_by_user"] = True
                    task["approved_at"] = task["approved_at"] or now_iso
                    task["rejected_at"] = None
                    task["rejection_reason"] = None
                    task["updated_at"] = now_iso
                return task, "ok"

            clean_reason = (str(reason or "").strip()[:500]) or None
            if task["status"] != "rejected":
                task["status"] = "rejected"
                task["approved_by_user"] = False
                task["rejected_at"] = task["rejected_at"] or now_iso
                task["approved_at"] = None
                task["rejection_reason"] = clean_reason
                task["updated_at"] = now_iso
            return task, "ok"
