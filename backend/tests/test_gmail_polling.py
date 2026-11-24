"""Integration tests for Phase 2 Gmail Polling Worker and authenticated /tasks endpoints."""

from __future__ import annotations

import base64
import sys
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient
from google.auth.exceptions import RefreshError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.encryption import encrypt_secret  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.session import Session as UserSession, User, utc_now  # noqa: E402
from app.models.task import GoogleOAuthToken, Task  # noqa: E402
from app.routes import tasks as task_routes  # noqa: E402
from app.services.gmail_poller import GmailPollingService  # noqa: E402


def _b64url(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


class _FakeExecute:
    def __init__(self, result: Any = None, exc: Exception | None = None) -> None:
        self._result = result
        self._exc = exc

    def execute(self) -> Any:
        if self._exc is not None:
            raise self._exc
        return self._result


class _FakeAttachmentsAPI:
    def __init__(self, attachments: Dict[str, str]) -> None:
        self._attachments = attachments

    def get(self, userId: str, messageId: str, id: str) -> _FakeExecute:
        return _FakeExecute({"data": self._attachments.get(id, "")})


class _FakeMessagesAPI:
    def __init__(
        self,
        messages: List[Dict[str, Any]],
        attachments: Dict[str, str] | None = None,
        list_error: Exception | None = None,
    ) -> None:
        self._messages = {m["id"]: m for m in messages}
        self._stubs = [{"id": m["id"]} for m in messages]
        self._attachments = attachments or {}
        self._list_error = list_error

    def list(self, userId: str, q: str, maxResults: int) -> _FakeExecute:
        return _FakeExecute({"messages": self._stubs[:maxResults]}, exc=self._list_error)

    def get(self, userId: str, id: str, format: str = "full") -> _FakeExecute:
        return _FakeExecute(self._messages[id])

    def attachments(self) -> _FakeAttachmentsAPI:
        return _FakeAttachmentsAPI(self._attachments)


class _FakeUsersAPI:
    def __init__(self, messages_api: _FakeMessagesAPI) -> None:
        self._messages_api = messages_api

    def messages(self) -> _FakeMessagesAPI:
        return self._messages_api


class _FakeGmailService:
    def __init__(
        self,
        messages: List[Dict[str, Any]],
        attachments: Dict[str, str] | None = None,
        list_error: Exception | None = None,
    ) -> None:
        self._users = _FakeUsersAPI(_FakeMessagesAPI(messages, attachments, list_error))

    def users(self) -> _FakeUsersAPI:
        return self._users


@pytest.fixture()
def db_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Isolated SQLite database with background scheduler disabled during tests."""
    monkeypatch.setenv("GMAIL_POLLING_ENABLED", "false")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-client-secret-placeholder")

    db_file = tmp_path / "test_gmail_polling.db"
    test_engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    Base.metadata.create_all(bind=test_engine)

    def _override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=test_engine)
        test_engine.dispose()


def _create_user_with_session(
    db,
    *,
    email: str,
    google_id: str,
    scopes: str = "openid email profile https://www.googleapis.com/auth/gmail.readonly",
    token_expired: bool = False,
    with_google_token: bool = True,
) -> tuple[User, str]:
    user = User(google_id=google_id, email=email, name=email.split("@")[0].title())
    db.add(user)
    db.flush()

    session_token = str(uuid.uuid4())
    now = utc_now()
    db.add(
        UserSession(
            id=session_token,
            user_id=user.id,
            created_at=now,
            expires_at=now + timedelta(days=30),
            is_active=True,
        )
    )

    if with_google_token:
        expiry = now - timedelta(minutes=10) if token_expired else now + timedelta(hours=1)
        db.add(
            GoogleOAuthToken(
                user_id=user.id,
                encrypted_access_token=encrypt_secret("fake-access-token"),
                encrypted_refresh_token=encrypt_secret("fake-refresh-token"),
                token_expiry=expiry,
                scopes=scopes,
                needs_reconnect=False,
            )
        )

    db.commit()
    return user, session_token


def _sample_ics_message(msg_id: str, summary: str) -> Dict[str, Any]:
    ics = "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "BEGIN:VEVENT",
            f"UID:{msg_id}@google.com",
            f"SUMMARY:{summary}",
            "DTSTART:20261210T180000Z",
            "DTEND:20261210T190000Z",
            "ORGANIZER;CN=Dana:mailto:dana@partner.com",
            "ATTENDEE:mailto:founder@joshu.app",
            "ATTENDEE:mailto:cfo@joshu.app",
            "URL:https://calendar.google.com/calendar/event?eid=sample99",
            "END:VEVENT",
            "END:VCALENDAR",
        ]
    )
    return {
        "id": msg_id,
        "threadId": f"thr-{msg_id}",
        "payload": {
            "headers": [
                {"name": "Subject", "value": f"Invitation: {summary}"},
                {"name": "From", "value": "dana@partner.com"},
            ],
            "parts": [
                {
                    "mimeType": "text/calendar",
                    "filename": "invite.ics",
                    "body": {"data": _b64url(ics)},
                }
            ],
        },
    }


def test_sync_and_list_tasks_are_authenticated_deduplicated_and_tenant_isolated(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, token_a = _create_user_with_session(
        db_session, email="alice@joshu.app", google_id="sub-alice"
    )
    _, token_b = _create_user_with_session(
        db_session, email="bob@joshu.app", google_id="sub-bob"
    )

    fake_messages = [
        _sample_ics_message("msg-101", "Investor Update Call"),
        {
            "id": "msg-non-invite",
            "payload": {
                "headers": [{"name": "Subject", "value": "Monthly Receipt"}],
                "parts": [{"mimeType": "text/plain", "body": {"data": _b64url("Thanks for paying.")}}],
            },
        },
    ]

    poller = GmailPollingService(
        gmail_service_factory=lambda _creds: _FakeGmailService(fake_messages)
    )
    monkeypatch.setattr(task_routes, "gmail_polling_service", poller)

    with TestClient(app) as client:
        # Unauthenticated request must fail with 401
        assert client.get("/tasks").status_code == 401

        # Trigger sync for Alice
        sync1 = client.post("/tasks/sync", headers={"Authorization": f"Bearer {token_a}"})
        assert sync1.status_code == 200
        body1 = sync1.json()
        assert body1["fetched_messages"] == 2
        assert body1["created_tasks"] == 1
        assert body1["ignored_non_invites"] == 1

        # Re-running sync must deduplicate cleanly
        sync2 = client.post("/tasks/sync", headers={"Authorization": f"Bearer {token_a}"})
        assert sync2.status_code == 200
        assert sync2.json()["created_tasks"] == 0
        assert sync2.json()["skipped_duplicates"] == 1

        # Alice sees her extracted task with meeting details
        alice_tasks = client.get("/tasks", headers={"Authorization": f"Bearer {token_a}"})
        assert alice_tasks.status_code == 200
        items = alice_tasks.json()["tasks"]
        assert len(items) == 1
        task = items[0]
        assert task["title"] == "Investor Update Call"
        assert task["source"] == "calendar"
        assert task["scheduled_for"] == "2026-12-10T18:00:00Z"
        assert task["attendees"] == ["founder@joshu.app", "cfo@joshu.app"]
        assert task["calendar_event_link"] == "https://calendar.google.com/calendar/event?eid=sample99"

        # Bob must not see Alice's task (list or direct GET by ID)
        bob_tasks = client.get("/tasks", headers={"Authorization": f"Bearer {token_b}"})
        assert bob_tasks.status_code == 200
        assert bob_tasks.json()["tasks"] == []

        bob_direct = client.get(
            f"/tasks/{task['id']}",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert bob_direct.status_code == 404


def test_sync_handles_expired_refresh_token_gracefully(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, token = _create_user_with_session(
        db_session,
        email="expired@joshu.app",
        google_id="sub-expired",
        token_expired=True,
    )

    from google.oauth2.credentials import Credentials

    def _raise_refresh_error(self, _request):
        raise RefreshError("Token has been expired or revoked.")

    monkeypatch.setattr(Credentials, "refresh", _raise_refresh_error)

    with TestClient(app) as client:
        res = client.post("/tasks/sync", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 403
        assert res.json()["error"] == "google_token_expired"

        status_res = client.get(
            "/tasks/sync/status",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert status_res.status_code == 200
        assert status_res.json()["google_reconnect_required"] is True

    db_session.expire_all()
    row = db_session.query(GoogleOAuthToken).filter_by(user_id=user.id).first()
    assert row is not None
    assert row.needs_reconnect is True


def test_sync_rejects_missing_gmail_scope_and_handles_network_errors(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, no_scope_token = _create_user_with_session(
        db_session,
        email="noscope@joshu.app",
        google_id="sub-noscope",
        scopes="openid email profile",
    )
    _, net_err_token = _create_user_with_session(
        db_session,
        email="neterr@joshu.app",
        google_id="sub-neterr",
    )

    failing_poller = GmailPollingService(
        gmail_service_factory=lambda _creds: _FakeGmailService(
            [], list_error=ConnectionError("DNS lookup failed")
        )
    )
    monkeypatch.setattr(task_routes, "gmail_polling_service", failing_poller)

    with TestClient(app) as client:
        scope_res = client.post(
            "/tasks/sync", headers={"Authorization": f"Bearer {no_scope_token}"}
        )
        assert scope_res.status_code == 403
        assert scope_res.json()["error"] == "scope_upgrade_required"

        net_res = client.post(
            "/tasks/sync", headers={"Authorization": f"Bearer {net_err_token}"}
        )
        assert net_res.status_code == 502
        assert net_res.json()["error"] == "gmail_api_error"


def test_poll_all_active_users_runs_across_multiple_tenants(db_session) -> None:
    user1, _ = _create_user_with_session(
        db_session, email="u1@joshu.app", google_id="sub-u1"
    )
    user2, _ = _create_user_with_session(
        db_session, email="u2@joshu.app", google_id="sub-u2"
    )

    poller = GmailPollingService(
        gmail_service_factory=lambda _creds: _FakeGmailService(
            [_sample_ics_message("msg-batch-1", "Weekly Executive Standup")]
        )
    )
    summary = poller.poll_all_active_users(db_session)
    assert summary["polled_users"] == 2
    assert summary["created_tasks"] == 2
    assert summary["errors"] == 0

    assert db_session.query(Task).filter_by(user_id=user1.id).count() == 1
    assert db_session.query(Task).filter_by(user_id=user2.id).count() == 1
