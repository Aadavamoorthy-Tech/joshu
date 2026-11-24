"""Integration tests for Phase 3 task approval/rejection endpoints and schema migration."""

from __future__ import annotations

import sys
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import Base, ensure_task_approval_columns, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.session import Session as UserSession, User, utc_now  # noqa: E402
from app.models.task import Task  # noqa: E402


@pytest.fixture()
def db_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GMAIL_POLLING_ENABLED", "false")
    db_file = tmp_path / "test_approval.db"
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


def _seed_user_and_task(
    db,
    *,
    email: str,
    google_id: str,
    title: str = "Team Standup",
    status: str = "pending",
) -> tuple[User, str, Task]:
    user = User(google_id=google_id, email=email, name=email.split("@")[0].title())
    db.add(user)
    db.flush()

    token = str(uuid.uuid4())
    now = utc_now()
    db.add(
        UserSession(
            id=token,
            user_id=user.id,
            created_at=now,
            expires_at=now + timedelta(days=30),
            is_active=True,
        )
    )

    task = Task(
        id=str(uuid.uuid4()),
        user_id=user.id,
        title=title,
        description="Organizer: manager@company.com",
        scheduled_for=now + timedelta(days=1),
        source="calendar",
        status=status,
        external_message_id=f"gmail-{uuid.uuid4().hex[:8]}",
        raw_data={
            "organizer": "manager@company.com",
            "attendees": ["manager@company.com", email],
            "calendar_event_link": "https://meet.google.com/abc-defg-hij",
        },
        created_at=now,
        updated_at=now,
    )
    db.add(task)
    db.commit()
    return user, token, task


def test_approve_task_is_idempotent_and_preserves_first_timestamp(db_session) -> None:
    _, token, task = _seed_user_and_task(
        db_session, email="owner@joshu.app", google_id="sub-owner-1"
    )

    with TestClient(app) as client:
        first = client.post(
            f"/tasks/{task.id}/approve",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert first.status_code == 200
        body1 = first.json()
        assert body1["task_id"] == task.id
        assert body1["status"] == "approved"
        assert body1["approved_at"] is not None
        assert body1["approved_by_user"] is True

        # Second call must be idempotent and keep original approved_at
        second = client.post(
            f"/tasks/{task.id}/approve",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert second.status_code == 200
        body2 = second.json()
        assert body2["status"] == "approved"
        assert body2["approved_at"] == body1["approved_at"]

        # GET /tasks/{id} returns approval metadata
        detail = client.get(
            f"/tasks/{task.id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert detail.status_code == 200
        assert detail.json()["status"] == "approved"
        assert detail.json()["approved_at"] == body1["approved_at"]
        assert detail.json()["approved_by_user"] is True


def test_reject_task_stores_optional_reason_and_is_idempotent(db_session) -> None:
    _, token, task = _seed_user_and_task(
        db_session, email="rejector@joshu.app", google_id="sub-reject-1"
    )

    with TestClient(app) as client:
        first = client.post(
            f"/tasks/{task.id}/reject",
            headers={"Authorization": f"Bearer {token}"},
            json={"reason": "Already have this meeting scheduled"},
        )
        assert first.status_code == 200
        body1 = first.json()
        assert body1["status"] == "rejected"
        assert body1["rejected_at"] is not None
        assert body1["rejection_reason"] == "Already have this meeting scheduled"

        # Calling reject again keeps the original rejected_at and reason
        second = client.post(
            f"/tasks/{task.id}/reject",
            headers={"Authorization": f"Bearer {token}"},
            json={"reason": "Different reason"},
        )
        assert second.status_code == 200
        assert second.json()["rejected_at"] == body1["rejected_at"]
        assert second.json()["rejection_reason"] == "Already have this meeting scheduled"


def test_status_filtering_counts_and_patch_rollback(db_session) -> None:
    user, token, pending_task = _seed_user_and_task(
        db_session, email="filter@joshu.app", google_id="sub-filter-1", title="Pending Sync"
    )
    now = utc_now()
    approved_task = Task(
        id=str(uuid.uuid4()),
        user_id=user.id,
        title="Approved Sync",
        description="",
        scheduled_for=now + timedelta(days=2),
        source="email",
        status="approved",
        approved_at=now,
        approved_by_user=True,
        raw_data={},
    )
    rejected_task = Task(
        id=str(uuid.uuid4()),
        user_id=user.id,
        title="Rejected Sync",
        description="",
        scheduled_for=now + timedelta(days=3),
        source="email",
        status="rejected",
        rejected_at=now,
        rejection_reason="Not relevant",
        approved_by_user=False,
        raw_data={},
    )
    db_session.add_all([approved_task, rejected_task])
    db_session.commit()

    with TestClient(app) as client:
        headers = {"Authorization": f"Bearer {token}"}

        all_res = client.get("/tasks?status=all", headers=headers)
        assert all_res.status_code == 200
        assert all_res.json()["total"] == 3
        assert all_res.json()["counts"] == {
            "all": 3,
            "pending": 1,
            "approved": 1,
            "rejected": 1,
        }

        pending_res = client.get("/tasks?status=pending", headers=headers)
        assert [t["id"] for t in pending_res.json()["tasks"]] == [pending_task.id]

        approved_res = client.get("/tasks?status=approved", headers=headers)
        assert [t["id"] for t in approved_res.json()["tasks"]] == [approved_task.id]

        rejected_res = client.get("/tasks?status=rejected", headers=headers)
        assert [t["id"] for t in rejected_res.json()["tasks"]] == [rejected_task.id]

        # Roll back approved -> pending via PATCH
        patch_res = client.patch(
            f"/tasks/{approved_task.id}",
            headers=headers,
            json={"status": "pending"},
        )
        assert patch_res.status_code == 200
        assert patch_res.json()["status"] == "pending"

        # Invalid status returns 400
        bad_patch = client.patch(
            f"/tasks/{approved_task.id}",
            headers=headers,
            json={"status": "archived"},
        )
        assert bad_patch.status_code == 400


def test_ownership_enforcement_returns_403_and_missing_returns_404(db_session) -> None:
    _, owner_token, task = _seed_user_and_task(
        db_session, email="alice@joshu.app", google_id="sub-alice-3"
    )
    _, other_token, _ = _seed_user_and_task(
        db_session, email="mallory@joshu.app", google_id="sub-mallory-3"
    )

    with TestClient(app) as client:
        # Unauthenticated -> 401
        assert client.post(f"/tasks/{task.id}/approve").status_code == 401

        # Cross-tenant approve/reject/patch -> 403 Forbidden
        other_headers = {"Authorization": f"Bearer {other_token}"}
        assert client.post(f"/tasks/{task.id}/approve", headers=other_headers).status_code == 403
        assert client.post(f"/tasks/{task.id}/reject", headers=other_headers).status_code == 403
        assert (
            client.patch(
                f"/tasks/{task.id}",
                headers=other_headers,
                json={"status": "approved"},
            ).status_code
            == 403
        )

        # Nonexistent task -> 404 Not Found
        missing_id = str(uuid.uuid4())
        owner_headers = {"Authorization": f"Bearer {owner_token}"}
        assert client.post(f"/tasks/{missing_id}/approve", headers=owner_headers).status_code == 404
        assert client.post(f"/tasks/{missing_id}/reject", headers=owner_headers).status_code == 404


def test_idempotent_schema_upgrade_adds_missing_approval_columns(tmp_path: Path) -> None:
    """Verify legacy Phase 2 `tasks` tables are upgraded cleanly without data loss."""
    legacy_db = tmp_path / "legacy_phase2.db"
    eng = create_engine(f"sqlite:///{legacy_db}", connect_args={"check_same_thread": False})
    with eng.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE tasks (
                    id VARCHAR(64) PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    title VARCHAR(500) NOT NULL,
                    description TEXT,
                    scheduled_for DATETIME,
                    source VARCHAR(32) NOT NULL DEFAULT 'email',
                    status VARCHAR(32) NOT NULL DEFAULT 'pending',
                    external_message_id VARCHAR(255),
                    raw_data JSON NOT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
        )

    # Running twice must be completely idempotent
    ensure_task_approval_columns(eng)
    ensure_task_approval_columns(eng)

    cols = {c["name"] for c in inspect(eng).get_columns("tasks")}
    assert {"approved_at", "rejected_at", "rejection_reason", "approved_by_user"}.issubset(cols)
    eng.dispose()
