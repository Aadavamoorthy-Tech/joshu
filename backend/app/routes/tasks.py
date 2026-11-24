"""Authenticated task listing, Gmail sync, and Phase 3 approval workflow endpoints."""

from __future__ import annotations

from datetime import timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session as DBSession

from app.database import SessionLocal, get_db
from app.middleware.auth import auth_error, get_current_session
from app.models.session import Session as UserSession, utc_now
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


class RejectTaskRequest(BaseModel):
    """Optional payload when rejecting a task."""

    reason: Optional[str] = Field(default=None, max_length=500)


class PatchTaskStatusRequest(BaseModel):
    """Payload for updating a task's approval status directly."""

    status: str = Field(..., min_length=1, max_length=32)
    rejection_reason: Optional[str] = Field(default=None, max_length=500)


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
        "approved_at": _format_utc(task.approved_at),
        "rejected_at": _format_utc(task.rejected_at),
        "rejection_reason": task.rejection_reason,
        "approved_by_user": bool(task.approved_by_user),
    }


def _get_owned_task_or_error(db: DBSession, task_id: str, user_id: int) -> Task:
    """Fetch a task by ID; raise 404 if missing or 403 if owned by a different user."""
    task = db.query(Task).filter(Task.id == task_id).first()
    if task is None:
        raise auth_error(404, "task_not_found", "Task not found")
    if task.user_id != user_id:
        raise auth_error(403, "forbidden", "You do not have permission to modify this task")
    return task


def _run_background_sync(user_id: int) -> None:
    db = SessionLocal()
    try:
        gmail_polling_service.poll_user_inbox(db, user_id)
    except Exception:
        # Errors are recorded on GoogleOAuthToken.last_error / needs_reconnect.
        pass
    finally:
        db.close()


def _status_counts_for_user(db: DBSession, user_id: int) -> Dict[str, int]:
    rows = (
        db.query(Task.status, func.count(Task.id))
        .filter(Task.user_id == user_id)
        .group_by(Task.status)
        .all()
    )
    counts = {"pending": 0, "approved": 0, "rejected": 0}
    for status_name, count in rows:
        if status_name in counts:
            counts[status_name] = int(count)
    counts["all"] = counts["pending"] + counts["approved"] + counts["rejected"]
    return counts


@router.get("")
def list_tasks(
    status: Optional[str] = Query(default=None),
    source: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_session: UserSession = Depends(get_current_session),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    """Return extracted tasks owned by the authenticated user with status filtering and counts."""
    query = db.query(Task).filter(Task.user_id == current_session.user_id)

    if status is not None:
        normalized_status = status.strip().lower()
        if normalized_status != "all":
            if normalized_status not in _VALID_STATUSES:
                raise auth_error(
                    400,
                    "invalid_status_filter",
                    "status must be one of: all, pending, approved, rejected",
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
        "counts": _status_counts_for_user(db, current_session.user_id),
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

    return _serialize_task(task)


@router.post("/{task_id}/approve")
def approve_task(
    task_id: str,
    current_session: UserSession = Depends(get_current_session),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    """Idempotently approve a task owned by the authenticated user."""
    task = _get_owned_task_or_error(db, task_id, current_session.user_id)

    if task.status != "approved":
        now = utc_now()
        task.status = "approved"
        task.approved_by_user = True
        if task.approved_at is None:
            task.approved_at = now
        task.updated_at = now
        try:
            db.commit()
            db.refresh(task)
        except Exception as exc:
            db.rollback()
            raise auth_error(500, "task_update_failed", "Failed to approve task") from exc

    return {
        "task_id": task.id,
        "status": task.status,
        "approved_at": _format_utc(task.approved_at),
        "approved_by_user": bool(task.approved_by_user),
        "task": _serialize_task(task),
        "message": "Task approved successfully",
    }


@router.post("/{task_id}/reject")
def reject_task(
    task_id: str,
    payload: Optional[RejectTaskRequest] = None,
    current_session: UserSession = Depends(get_current_session),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    """Idempotently reject a task owned by the authenticated user with an optional reason."""
    task = _get_owned_task_or_error(db, task_id, current_session.user_id)
    cleaned_reason = (
        payload.reason.strip() if payload and payload.reason and payload.reason.strip() else None
    )

    changed = False
    now = utc_now()
    if task.status != "rejected":
        task.status = "rejected"
        task.approved_by_user = False
        if task.rejected_at is None:
            task.rejected_at = now
        if cleaned_reason is not None:
            task.rejection_reason = cleaned_reason
        task.updated_at = now
        changed = True
    elif cleaned_reason is not None and not task.rejection_reason:
        task.rejection_reason = cleaned_reason
        task.updated_at = now
        changed = True

    if changed:
        try:
            db.commit()
            db.refresh(task)
        except Exception as exc:
            db.rollback()
            raise auth_error(500, "task_update_failed", "Failed to reject task") from exc

    return {
        "task_id": task.id,
        "status": task.status,
        "rejected_at": _format_utc(task.rejected_at),
        "rejection_reason": task.rejection_reason,
        "task": _serialize_task(task),
        "message": "Task rejected successfully",
    }


@router.patch("/{task_id}")
def patch_task_status(
    task_id: str,
    payload: PatchTaskStatusRequest,
    current_session: UserSession = Depends(get_current_session),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    """Update a task's status (e.g., rollback approved/rejected -> pending)."""
    normalized_status = payload.status.strip().lower()
    if normalized_status not in _VALID_STATUSES:
        raise auth_error(
            400,
            "invalid_status",
            "status must be one of: pending, approved, rejected",
        )

    task = _get_owned_task_or_error(db, task_id, current_session.user_id)
    now = utc_now()
    task.status = normalized_status

    if normalized_status == "approved":
        task.approved_by_user = True
        if task.approved_at is None:
            task.approved_at = now
    elif normalized_status == "rejected":
        task.approved_by_user = False
        if task.rejected_at is None:
            task.rejected_at = now
        if payload.rejection_reason is not None:
            cleaned = payload.rejection_reason.strip()
            task.rejection_reason = cleaned or None
    else:
        task.approved_by_user = False

    task.updated_at = now
    try:
        db.commit()
        db.refresh(task)
    except Exception as exc:
        db.rollback()
        raise auth_error(500, "task_update_failed", "Failed to update task status") from exc

    return {
        "task_id": task.id,
        "status": task.status,
        "task": _serialize_task(task),
        "message": "Task status updated successfully",
    }
