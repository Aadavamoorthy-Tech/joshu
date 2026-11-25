"""Unit and integration tests for FastAPI OAuth sign-in, callback, refresh, and logout flows."""

from __future__ import annotations

import sys
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.session import OAuthState, Session as UserSession, User, utc_now  # noqa: E402
from app.models.task import GoogleOAuthToken  # noqa: E402
from app.routes import auth as auth_routes  # noqa: E402


@pytest.fixture()
def db_session(tmp_path: Path):
    """Provide an isolated SQLite database per test."""
    db_file = tmp_path / "test_auth.db"
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


@pytest.fixture()
def configured_oauth(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configure deterministic non-secret OAuth test credentials."""
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-client-secret-placeholder")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/callback")
    monkeypatch.setenv("SESSION_TOKEN_EXPIRY_DAYS", "30")


class _FakeFlow:
    """Stub Google OAuth Flow avoiding outbound network calls in unit tests."""

    def __init__(self, redirect_uri: str, fail_fetch: bool = False) -> None:
        self.redirect_uri = redirect_uri
        self.fail_fetch = fail_fetch
        self.credentials = None

    def authorization_url(self, **kwargs: Any) -> tuple[str, str]:
        state = kwargs["state"]
        url = (
            "https://accounts.google.com/o/oauth2/v2/auth"
            f"?client_id=test-client-id.apps.googleusercontent.com"
            f"&redirect_uri={self.redirect_uri}"
            f"&scope=openid+email+profile+https://www.googleapis.com/auth/gmail.readonly"
            f"&state={state}"
        )
        return url, state

    def fetch_token(self, code: str) -> dict[str, Any]:
        if self.fail_fetch or code == "bad-code":
            raise ValueError("invalid_grant")
        return {
            "access_token": "google-access-token-never-returned",
            "refresh_token": "google-refresh-token-never-returned",
            "id_token": "signed-google-id-token",
        }


def test_signin_returns_redirect_url_and_stores_state(
    db_session,
    configured_oauth,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        auth_routes,
        "_build_google_flow",
        lambda cid, csec, uri: _FakeFlow(uri),
    )

    with TestClient(app) as client:
        response = client.post("/auth/signin")

    assert response.status_code == 200
    body = response.json()
    assert "redirect_url" in body
    parsed = urlparse(body["redirect_url"])
    qs = parse_qs(parsed.query)
    assert "state" in qs
    assert "openid" in qs["scope"][0]
    assert "https://www.googleapis.com/auth/gmail.readonly" in auth_routes.OAUTH_SCOPES

    stored = db_session.query(OAuthState).filter_by(state=qs["state"][0]).first()
    assert stored is not None


def test_signin_returns_500_when_oauth_not_configured(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)

    with TestClient(app) as client:
        response = client.post("/auth/signin")

    assert response.status_code == 500
    body = response.json()
    assert body["error"] == "oauth_not_configured"
    assert body["status"] == 500


def test_callback_creates_user_and_30_day_uuid_session(
    db_session,
    configured_oauth,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        auth_routes,
        "_build_google_flow",
        lambda cid, csec, uri: _FakeFlow(uri),
    )
    monkeypatch.setattr(
        auth_routes,
        "_verify_google_id_token",
        lambda raw, cid: {
            "sub": "google-sub-123",
            "email": "Founder@Example.com",
            "name": "Alex Founder",
            "picture": "https://example.com/avatar.png",
        },
    )

    with TestClient(app) as client:
        signin = client.post("/auth/signin")
        state = parse_qs(urlparse(signin.json()["redirect_url"]).query)["state"][0]

        callback = client.get("/auth/callback", params={"code": "valid-code", "state": state})

    assert callback.status_code == 200
    data = callback.json()
    assert "session_token" in data
    # Verify opaque UUID session token
    uuid.UUID(data["session_token"])
    assert data["user"] == {
        "email": "founder@example.com",
        "name": "Alex Founder",
        "picture_url": "https://example.com/avatar.png",
    }
    assert "access_token" not in data
    assert "refresh_token" not in data

    # Verify DB persistence & 30-day TTL
    db_session.expire_all()
    user = db_session.query(User).filter_by(google_id="google-sub-123").first()
    assert user is not None
    session_row = db_session.query(UserSession).filter_by(id=data["session_token"]).first()
    assert session_row is not None
    assert session_row.is_active is True
    delta = session_row.expires_at - session_row.created_at
    assert delta == timedelta(days=30)

    # Verify Google OAuth credentials were persisted encrypted (never plaintext)
    token_row = db_session.query(GoogleOAuthToken).filter_by(user_id=user.id).first()
    assert token_row is not None
    assert token_row.encrypted_access_token != "google-access-token-never-returned"
    assert token_row.encrypted_refresh_token != "google-refresh-token-never-returned"
    assert token_row.has_gmail_readonly() is True

    # Replaying the same state must fail with 400
    with TestClient(app) as client:
        replay = client.get("/auth/callback", params={"code": "valid-code", "state": state})
    assert replay.status_code == 400
    assert replay.json()["error"] == "invalid_state"


def test_callback_updates_existing_user_without_duplicates(
    db_session,
    configured_oauth,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        auth_routes,
        "_build_google_flow",
        lambda cid, csec, uri: _FakeFlow(uri),
    )
    monkeypatch.setattr(
        auth_routes,
        "_verify_google_id_token",
        lambda raw, cid: {
            "sub": "google-sub-dup",
            "email": "user@example.com",
            "name": "Updated Name",
            "picture": None,
        },
    )

    with TestClient(app) as client:
        for _ in range(2):
            signin = client.post("/auth/signin")
            state = parse_qs(urlparse(signin.json()["redirect_url"]).query)["state"][0]
            res = client.get("/auth/callback", params={"code": "ok-code", "state": state})
            assert res.status_code == 200

    db_session.expire_all()
    users = db_session.query(User).filter_by(google_id="google-sub-dup").all()
    assert len(users) == 1
    assert users[0].name == "Updated Name"


def test_callback_rejects_missing_code_or_invalid_state(
    db_session,
    configured_oauth,
) -> None:
    with TestClient(app) as client:
        missing_code = client.get("/auth/callback", params={"state": "abc"})
        bad_state = client.get("/auth/callback", params={"code": "abc", "state": "forged"})

    assert missing_code.status_code == 400
    assert missing_code.json()["error"] == "missing_code"
    assert bad_state.status_code == 400
    assert bad_state.json()["error"] == "invalid_state"


def test_refresh_rotates_session_and_invalidates_old_token(
    db_session,
    configured_oauth,
) -> None:
    user = User(google_id="sub-refresh", email="r@example.com", name="Refresh User")
    db_session.add(user)
    db_session.flush()

    old_token = str(uuid.uuid4())
    now = utc_now()
    db_session.add(
        UserSession(
            id=old_token,
            user_id=user.id,
            created_at=now,
            expires_at=now + timedelta(days=30),
            is_active=True,
        )
    )
    db_session.commit()

    with TestClient(app) as client:
        res = client.post("/auth/refresh", headers={"Authorization": f"Bearer {old_token}"})
        assert res.status_code == 200
        new_token = res.json()["session_token"]
        assert new_token != old_token
        uuid.UUID(new_token)

        # Old token must now be rejected
        old_retry = client.post("/auth/refresh", headers={"Authorization": f"Bearer {old_token}"})
        assert old_retry.status_code == 401

        # New token must work on /auth/me
        me = client.get("/auth/me", headers={"Authorization": f"Bearer {new_token}"})
        assert me.status_code == 200
        assert me.json()["user"]["email"] == "r@example.com"


def test_logout_deactivates_session_and_rejects_expired_tokens(
    db_session,
    configured_oauth,
) -> None:
    user = User(google_id="sub-logout", email="l@example.com", name="Logout User")
    db_session.add(user)
    db_session.flush()

    active_token = str(uuid.uuid4())
    expired_token = str(uuid.uuid4())
    now = utc_now()
    db_session.add_all(
        [
            UserSession(
                id=active_token,
                user_id=user.id,
                created_at=now,
                expires_at=now + timedelta(days=30),
                is_active=True,
            ),
            UserSession(
                id=expired_token,
                user_id=user.id,
                created_at=now - timedelta(days=31),
                expires_at=now - timedelta(days=1),
                is_active=True,
            ),
        ]
    )
    db_session.commit()

    with TestClient(app) as client:
        missing_auth = client.post("/auth/logout")
        assert missing_auth.status_code == 401

        not_found = client.post(
            "/auth/logout",
            headers={"Authorization": f"Bearer {uuid.uuid4()}"},
        )
        assert not_found.status_code == 404

        expired_res = client.post(
            "/auth/refresh",
            headers={"Authorization": f"Bearer {expired_token}"},
        )
        assert expired_res.status_code == 401

        logout_res = client.post(
            "/auth/logout",
            headers={"Authorization": f"Bearer {active_token}"},
        )
        assert logout_res.status_code == 200
        assert logout_res.json() == {"message": "Logged out successfully"}

        after_logout = client.post(
            "/auth/refresh",
            headers={"Authorization": f"Bearer {active_token}"},
        )
        assert after_logout.status_code == 401

    db_session.expire_all()
    row = db_session.query(UserSession).filter_by(id=active_token).first()
    assert row is not None
    assert row.is_active is False


def test_httponly_cookie_persists_across_refresh_and_enforces_csrf(
    db_session,
    configured_oauth,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        auth_routes,
        "_build_google_flow",
        lambda cid, csec, uri: _FakeFlow(uri),
    )
    monkeypatch.setattr(
        auth_routes,
        "_verify_google_id_token",
        lambda raw, cid: {
            "sub": "google-sub-cookie",
            "email": "cookie@example.com",
            "name": "Cookie User",
            "picture": None,
        },
    )

    with TestClient(app) as client:
        signin = client.post("/auth/signin")
        state = parse_qs(urlparse(signin.json()["redirect_url"]).query)["state"][0]

        callback = client.get("/auth/callback", params={"code": "valid-code", "state": state})
        assert callback.status_code == 200
        set_cookie = callback.headers.get("set-cookie", "")
        assert "joshu_session=" in set_cookie
        assert "HttpOnly" in set_cookie

        # Simulated page refresh: /auth/me succeeds with HttpOnly cookie only
        me = client.get("/auth/me")
        assert me.status_code == 200
        assert me.json()["user"]["email"] == "cookie@example.com"

        # Mutating cookie request without X-Requested-With is blocked
        blocked = client.post("/auth/refresh")
        assert blocked.status_code == 403
        assert blocked.json()["error"] == "csrf_header_required"

        # Mutating cookie request with X-Requested-With succeeds
        refreshed = client.post("/auth/refresh", headers={"X-Requested-With": "fetch"})
        assert refreshed.status_code == 200

        # Logout revokes session and clears cookie
        out = client.post("/auth/logout", headers={"X-Requested-With": "fetch"})
        assert out.status_code == 200
        assert "Max-Age=0" in out.headers.get("set-cookie", "")

        after_out = client.get("/auth/me")
        assert after_out.status_code == 401
