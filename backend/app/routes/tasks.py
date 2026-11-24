"""Authenticated task listing and on-demand Gmail polling endpoints."""

from __future__ import annotations

from datetime import timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session as DBSession

from app.database import SessionLocal, get_db
from app.middleware.auth import auth_error, get_current_session
from app.models.session import Session as UserSession
from app.models.task import GoogleOAuthToken, Task
from app.services.gmail_poller import (
    GmailApiError,
    GmailScopeMissingError,
    GoogleTokenExpiredError,
    get_poll_interval_minutes,
    gmail_polling_scheduler,
    gmail_polling_service,
)

router = APIRouter(prefix="/tasks", tags=["tasks"])

_VALID_SOURCES = {"email", "calendar"}
_VALID_STATUSES = {"pending", "approved", "rejected"}


def _format_utc(dt) -> Optional[str]:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def _serialize_task(task: Task) -> Dict[str, Any]:
    raw = task.raw_data if isinstance(task.raw_data, dict) else {}
    return {
        "id": task.id,
        "user_id": task.user_id,
        "title": task.title,
        "description": task.description or "",
        "scheduled_for": _format_utc(task.scheduled_for),
        "source": task.source,
        "status": task.status,
        "attendees": raw.get("attendees") or [],
        "organizer": raw.get("organizer"),
        "calendar_event_link": raw.get("calendar_event_link"),
        "raw_data": raw,
        "created_at": _format_utc(task.created_at),
        "updated_at": _format_utc(task.updated_at),
    }


def _run_background_sync(user_id: int) -> None:
    db = SessionLocal()
    try:
        gmail_polling_service.poll_user_inbox(db, user_id)
    except Exception:
        # Errors are recorded on GoogleOAuthToken.last_error / needs_reconnect.
        pass
    finally:
        db.close()


@router.get("")
def list_tasks(
    status: Optional[str] = Query(default=None),
    source: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_session: UserSession = Depends(get_current_session),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    """Return extracted tasks owned by the authenticated user."""
    query = db.query(Task).filter(Task.user_id == current_session.user_id)

    if status is not None:
        normalized_status = status.strip().lower()
        if normalized_status not in _VALID_STATUSES:
            raise auth_error(
                400,
                "invalid_status_filter",
                "status must be one of: pending, approved, rejected",
            )
        query = query.filter(Task.status == normalized_status)

    if source is not None:
        normalized_source = source.strip().lower()
        if normalized_source not in _VALID_SOURCES:
            raise auth_error(
                400,
                "invalid_source_filter",
                "source must be one of: email, calendar",
            )
        query = query.filter(Task.source == normalized_source)

    total = query.count()
    items: List[Task] = (
        query.order_by(Task.scheduled_for.desc(), Task.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return {
        "tasks": [_serialize_task(item) for item in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/sync/status")
def get_sync_status(
    current_session: UserSession = Depends(get_current_session),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    """Return Gmail polling status and schedule metadata for the authenticated user."""
    token_record = (
        db.query(GoogleOAuthToken)
        .filter(GoogleOAuthToken.user_id == current_session.user_id)
        .first()
    )

    return {
        "gmail_connected": token_record is not None and token_record.has_gmail_readonly(),
        "google_reconnect_required": bool(token_record.needs_reconnect) if token_record else True,
        "last_synced_at": _format_utc(token_record.last_synced_at) if token_record else None,
        "last_error": token_record.last_error if token_record else None,
        "poll_interval_minutes": get_poll_interval_minutes(),
        "scheduler_running": gmail_polling_scheduler.is_running,
    }


@router.post("/sync")
def trigger_gmail_sync(
    background_tasks: BackgroundTasks,
    background: bool = Query(default=False),
    current_session: UserSession = Depends(get_current_session),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    """Trigger Gmail invitation polling for the authenticated user (sync or background)."""
    if background:
        background_tasks.add_task(_run_background_sync, current_session.user_id)
        return {
            "status": "queued",
            "message": "Gmail polling scheduled in background",
        }

    try:
        result = gmail_polling_service.poll_user_inbox(db, current_session.user_id)
    except GoogleTokenExpiredError as exc:
        raise auth_error(403, "google_token_expired", str(exc)) from exc
    except GmailScopeMissingError as exc:
        raise auth_error(403, "scope_upgrade_required", str(exc)) from exc
    except GmailApiError as exc:
        raise auth_error(502, "gmail_api_error", str(exc)) from exc

    return {
        "status": "completed",
        "fetched_messages": result.fetched_messages,
        "created_tasks": result.created_tasks,
        "skipped_duplicates": result.skipped_duplicates,
        "ignored_non_invites": result.ignored_non_invites,
        "synced_at": result.synced_at,
    }


@router.get("/{task_id}")
def get_task(
    task_id: str,
    current_session: UserSession = Depends(get_current_session),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    """Return a single extracted task if owned by the authenticated user."""
    task = (
        db.query(Task)
        .filter(Task.id == task_id, Task.user_id == current_session.user_id)
        .first()
    )
    if task is None:
        raise auth_error(404, "task_not_found", "Task not found")

    return {"task": _serialize_task(task)}
