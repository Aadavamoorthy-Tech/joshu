"""Authenticated task listing, Gmail sync, AI email comprehension, and real action execution endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm.attributes import flag_modified

from app.database import SessionLocal, get_db
from app.middleware.auth import auth_error, get_current_session
from app.models.session import Session as UserSession, utc_now
from app.models.task import GoogleOAuthToken, Task
from app.services.email_analyzer import (
    EmailAnalysisApiError,
    EmailAnalysisConfigError,
    analyze_email_with_gemini,
)
from app.services.gmail_poller import (
    GmailApiError,
    GmailScopeMissingError,
    GoogleTokenExpiredError,
    get_poll_interval_minutes,
    gmail_polling_scheduler,
    gmail_polling_service,
)
from app.services.google_actions import (
    GoogleActionError,
    ScopeUpgradeRequiredError,
    get_processed_folder_name,
    google_actions_service,
)
from app.services.payment_executor import (
    PaymentExecutionError,
    PaymentGatewayNotConfiguredError,
    PaymentValidationError,
    payment_executor_service,
)

router = APIRouter(prefix="/tasks", tags=["tasks"])

_VALID_SOURCES = {"email", "calendar"}
_VALID_STATUSES = {"pending", "approved", "rejected"}


class ApproveTaskRequest(BaseModel):
    """Optional approval payload allowing edited reply drafts, calendar details, or payment confirmation."""

    send_reply: Optional[bool] = None
    reply_to: Optional[str] = Field(default=None, max_length=254)
    reply_subject: Optional[str] = Field(default=None, max_length=250)
    reply_body: Optional[str] = Field(default=None, max_length=4000)

    add_to_calendar: Optional[bool] = None
    calendar_title: Optional[str] = Field(default=None, max_length=250)
    calendar_start_iso: Optional[str] = Field(default=None, max_length=64)
    calendar_end_iso: Optional[str] = Field(default=None, max_length=64)
    calendar_location: Optional[str] = Field(default=None, max_length=300)
    calendar_attendees: Optional[List[str]] = None

    execute_payment: Optional[bool] = None
    payment_amount: Optional[float] = Field(default=None, gt=0)
    payment_currency: Optional[str] = Field(default=None, max_length=10)
    payment_payee: Optional[str] = Field(default=None, max_length=160)
    payment_upi_id: Optional[str] = Field(default=None, max_length=160)
    payment_bank_account: Optional[str] = Field(default=None, max_length=32)
    payment_ifsc: Optional[str] = Field(default=None, max_length=16)
    payment_mode: Optional[str] = Field(default=None, max_length=16)

    mark_read_and_move: bool = True
    target_folder: Optional[str] = Field(default=None, max_length=100)


class RejectTaskRequest(BaseModel):
    """Optional payload when rejecting a task."""

    reason: Optional[str] = Field(default=None, max_length=500)
    mark_read_and_move: bool = True
    target_folder: Optional[str] = Field(default=None, max_length=100)


class PatchTaskStatusRequest(BaseModel):
    """Payload for updating a task's approval status directly."""

    status: str = Field(..., min_length=1, max_length=32)
    rejection_reason: Optional[str] = Field(default=None, max_length=500)


def _format_utc(dt) -> Optional[str]:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


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


def _serialize_task(task: Task) -> Dict[str, Any]:
    raw = task.raw_data if isinstance(task.raw_data, dict) else {}
    ai_analysis = raw.get("ai_analysis") if isinstance(raw.get("ai_analysis"), dict) else None
    execution_log = raw.get("execution_log") if isinstance(raw.get("execution_log"), dict) else None
    action_category = (
        ai_analysis.get("category")
        if ai_analysis and ai_analysis.get("category")
        else ("meeting_invite" if task.source == "calendar" else "informational")
    )
    recommended_action = (
        ai_analysis.get("recommended_action")
        if ai_analysis and ai_analysis.get("recommended_action")
        else (
            f"Add '{task.title}' to Google Calendar and mark email read?"
            if task.source == "calendar"
            else "Review this email, mark read, and move to processed folder?"
        )
    )

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
        "action_category": action_category,
        "recommended_action": recommended_action,
        "ai_analysis": ai_analysis,
        "ai_analysis_error": raw.get("ai_analysis_error"),
        "execution_log": execution_log,
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


def _analyze_and_persist_task(db: DBSession, task: Task, user_name: str, user_email: str) -> Dict[str, Any]:
    raw = dict(task.raw_data) if isinstance(task.raw_data, dict) else {}
    existing_cal = None
    if task.source == "calendar":
        existing_cal = {
            "title": task.title,
            "start_iso": _format_utc(task.scheduled_for) or "",
            "end_iso": raw.get("end_time") or "",
            "location": raw.get("location") or "",
            "description": task.description or "",
            "attendees": raw.get("attendees") or [],
        }

    analysis = analyze_email_with_gemini(
        subject=task.title,
        sender=str(raw.get("organizer") or "Unknown Sender"),
        body=task.description or "",
        received_at_iso=_format_utc(task.scheduled_for) or _format_utc(task.created_at),
        reply_to=raw.get("reply_to") or raw.get("organizer"),
        existing_calendar=existing_cal,
        user_name=user_name,
        user_email=user_email,
    )

    raw["ai_analysis"] = analysis
    raw.pop("ai_analysis_error", None)
    task.raw_data = raw
    flag_modified(task, "raw_data")

    cal_info = analysis.get("calendar_event") or {}
    if analysis.get("requires_calendar") and cal_info.get("start_iso"):
        parsed_start = _parse_iso_naive_utc(cal_info.get("start_iso"))
        if parsed_start is not None:
            task.scheduled_for = parsed_start
        task.source = "calendar"

    task.updated_at = utc_now()
    db.commit()
    db.refresh(task)
    return analysis


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
        "gmail_modify_granted": token_record is not None and token_record.has_gmail_modify(),
        "gmail_send_granted": token_record is not None and token_record.has_gmail_send(),
        "calendar_granted": token_record is not None and token_record.has_calendar_events(),
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
    """Trigger Gmail invitation & inbox polling for the authenticated user."""
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


@router.post("/analyze-pending")
def analyze_pending_tasks(
    force: bool = Query(default=False),
    limit: int = Query(default=15, ge=1, le=50),
    current_session: UserSession = Depends(get_current_session),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    """Analyze pending emails with Gemini AI to draft replies and extract payment/meeting/RSVP actions."""
    user = current_session.user
    pending_tasks = (
        db.query(Task)
        .filter(Task.user_id == current_session.user_id, Task.status == "pending")
        .order_by(Task.created_at.desc())
        .limit(limit)
        .all()
    )

    analyzed = 0
    skipped = 0
    failed = 0
    last_error: Optional[str] = None

    for task in pending_tasks:
        raw = task.raw_data if isinstance(task.raw_data, dict) else {}
        if not force and isinstance(raw.get("ai_analysis"), dict):
            skipped += 1
            continue
        try:
            _analyze_and_persist_task(db, task, user.name, user.email)
            analyzed += 1
        except EmailAnalysisConfigError as exc:
            raise auth_error(503, "ai_not_configured", str(exc)) from exc
        except EmailAnalysisApiError as exc:
            failed += 1
            last_error = str(exc)
            updated_raw = dict(raw)
            updated_raw["ai_analysis_error"] = str(exc)
            task.raw_data = updated_raw
            flag_modified(task, "raw_data")
            db.commit()
            if exc.status_code in (400, 403, 404):
                raise auth_error(502, "ai_analysis_failed", str(exc)) from exc

    return {
        "status": "completed",
        "analyzed": analyzed,
        "skipped": skipped,
        "failed": failed,
        "last_error": last_error,
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


@router.post("/{task_id}/analyze")
def analyze_single_task(
    task_id: str,
    current_session: UserSession = Depends(get_current_session),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    """Run Gemini AI comprehension on a single email task owned by the authenticated user."""
    task = _get_owned_task_or_error(db, task_id, current_session.user_id)
    user = current_session.user
    try:
        analysis = _analyze_and_persist_task(db, task, user.name, user.email)
    except EmailAnalysisConfigError as exc:
        raise auth_error(503, "ai_not_configured", str(exc)) from exc
    except EmailAnalysisApiError as exc:
        status_code = 429 if exc.status_code == 429 else 502
        raise auth_error(status_code, "ai_analysis_failed", str(exc)) from exc

    return {
        "task_id": task.id,
        "ai_analysis": analysis,
        "task": _serialize_task(task),
    }


@router.post("/{task_id}/approve")
def approve_task(
    task_id: str,
    payload: Optional[ApproveTaskRequest] = None,
    current_session: UserSession = Depends(get_current_session),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    """Approve a task and automatically execute approved actions (reply, RSVP, Calendar, payment, and Gmail archive)."""
    task = _get_owned_task_or_error(db, task_id, current_session.user_id)
    raw = dict(task.raw_data) if isinstance(task.raw_data, dict) else {}

    # Idempotency guard: never double-send emails, double-create events, or double-charge payments.
    if task.status == "approved":
        return {
            "task_id": task.id,
            "status": task.status,
            "approved_at": _format_utc(task.approved_at),
            "approved_by_user": bool(task.approved_by_user),
            "execution_log": raw.get("execution_log") or {},
            "task": _serialize_task(task),
            "message": "Task was already approved and executed",
        }

    ai = raw.get("ai_analysis") if isinstance(raw.get("ai_analysis"), dict) else {}
    token_record = google_actions_service.get_token_record(db, current_session.user_id)
    gmail_msg_id = str(raw.get("gmail_message_id") or task.external_message_id or "").strip()

    do_reply = (
        payload.send_reply
        if payload is not None and payload.send_reply is not None
        else bool(ai.get("requires_reply") or ai.get("requires_rsvp"))
    )
    do_calendar = (
        payload.add_to_calendar
        if payload is not None and payload.add_to_calendar is not None
        else bool(
            ai.get("requires_calendar")
            or ai.get("requires_rsvp")
            or (task.source == "calendar" and token_record is not None and task.scheduled_for is not None)
        )
    )
    do_payment = (
        payload.execute_payment
        if payload is not None and payload.execute_payment is not None
        else bool(ai.get("requires_payment"))
    )
    do_archive = (
        payload.mark_read_and_move if payload is not None else True
    ) and bool(gmail_msg_id) and token_record is not None

    # Pre-flight Google OAuth scope verification so multi-step actions (e.g. RSVP + Calendar + Archive)
    # fail cleanly before partial execution if the user needs to reconnect Google once.
    if (do_reply or do_calendar or do_archive) and token_record is not None:
        missing_scopes: List[str] = []
        if do_reply and not token_record.has_gmail_send():
            missing_scopes.append("Gmail Send")
        if do_calendar and not token_record.has_calendar_events():
            missing_scopes.append("Google Calendar")
        if do_archive and not token_record.has_gmail_modify():
            missing_scopes.append("Gmail Modify (mark read & move folder)")
        if missing_scopes:
            raise auth_error(
                403,
                "scope_upgrade_required",
                f"Additional Google permissions required ({', '.join(missing_scopes)}). "
                "Click Logout and Sign In with Google once to enable automatic replies, Calendar events, and inbox archiving.",
            )

    execution_log: Dict[str, Any] = dict(raw.get("execution_log") or {})
    completed_steps: List[str] = []

    # 1. Execute automatic payment if required/requested
    if do_payment:
        ai_pay = ai.get("payment") if isinstance(ai.get("payment"), dict) else {}
        amount = (
            payload.payment_amount
            if payload is not None and payload.payment_amount is not None
            else ai_pay.get("amount")
        )
        currency = (
            payload.payment_currency
            if payload is not None and payload.payment_currency
            else (ai_pay.get("currency") or "INR")
        )
        payee_name = (
            payload.payment_payee
            if payload is not None and payload.payment_payee
            else (ai_pay.get("payee_name") or raw.get("organizer") or task.title)
        )
        payee_upi_id = (
            payload.payment_upi_id
            if payload is not None and payload.payment_upi_id is not None
            else (ai_pay.get("payee_upi_id") or "")
        )
        payee_bank_account = (
            payload.payment_bank_account
            if payload is not None and payload.payment_bank_account is not None
            else (ai_pay.get("payee_bank_account") or "")
        )
        payee_ifsc = (
            payload.payment_ifsc
            if payload is not None and payload.payment_ifsc is not None
            else (ai_pay.get("payee_ifsc") or "")
        )
        payment_mode = (
            payload.payment_mode
            if payload is not None and payload.payment_mode is not None
            else ""
        )
        try:
            payment_result = payment_executor_service.execute_payment(
                task_id=task.id,
                user_email=current_session.user.email,
                amount=float(amount or 0),
                currency=str(currency),
                payee_name=str(payee_name),
                payee_email=str(ai_pay.get("payee_email") or ""),
                payee_upi_id=str(payee_upi_id),
                payee_bank_account=str(payee_bank_account),
                payee_ifsc=str(payee_ifsc),
                payment_mode=str(payment_mode),
                invoice_number=str(ai_pay.get("invoice_number") or ""),
                payment_reference=str(ai_pay.get("payment_reference") or ""),
            )
            execution_log["payment"] = payment_result
            completed_steps.append(
                f"Payment of {payment_result['amount']:.2f} {payment_result['currency']} sent automatically ({payment_result['payment_id']})"
            )
        except PaymentGatewayNotConfiguredError as exc:
            raise auth_error(422, "payment_gateway_not_configured", str(exc)) from exc
        except PaymentValidationError as exc:
            raise auth_error(400, "invalid_payment", str(exc)) from exc
        except PaymentExecutionError as exc:
            raise auth_error(502, "payment_failed", str(exc)) from exc

    # 2. Add meeting to Google Calendar if required/requested
    if do_calendar:
        ai_cal = ai.get("calendar_event") if isinstance(ai.get("calendar_event"), dict) else {}
        cal_title = (
            payload.calendar_title
            if payload is not None and payload.calendar_title
            else (ai_cal.get("title") or task.title)
        )
        cal_start = (
            payload.calendar_start_iso
            if payload is not None and payload.calendar_start_iso
            else (ai_cal.get("start_iso") or _format_utc(task.scheduled_for) or "")
        )
        cal_end = (
            payload.calendar_end_iso
            if payload is not None and payload.calendar_end_iso
            else (ai_cal.get("end_iso") or raw.get("end_time"))
        )
        cal_location = (
            payload.calendar_location
            if payload is not None and payload.calendar_location is not None
            else (ai_cal.get("location") or raw.get("location") or "")
        )
        cal_attendees = (
            payload.calendar_attendees
            if payload is not None and payload.calendar_attendees is not None
            else (ai_cal.get("attendees") or raw.get("attendees") or [])
        )
        try:
            cal_result = google_actions_service.create_calendar_event(
                db,
                current_session.user_id,
                title=str(cal_title),
                start_iso=str(cal_start),
                end_iso=str(cal_end) if cal_end else None,
                description=str(ai_cal.get("description") or task.description or ""),
                location=str(cal_location),
                attendees=list(cal_attendees),
            )
            execution_log["calendar"] = cal_result
            if cal_result.get("html_link"):
                raw["calendar_event_link"] = cal_result["html_link"]
            completed_steps.append("Added to Google Calendar")
        except ScopeUpgradeRequiredError as exc:
            raise auth_error(403, "scope_upgrade_required", str(exc)) from exc
        except GoogleTokenExpiredError as exc:
            raise auth_error(403, "google_token_expired", str(exc)) from exc
        except GoogleActionError as exc:
            raise auth_error(400, "calendar_action_failed", str(exc)) from exc

    # 3. Send drafted reply / RSVP email if required/requested
    if do_reply:
        ai_draft = ai.get("draft_reply") if isinstance(ai.get("draft_reply"), dict) else {}
        reply_to = (
            payload.reply_to
            if payload is not None and payload.reply_to
            else (ai_draft.get("to") or raw.get("reply_to") or raw.get("organizer") or "")
        )
        reply_subject = (
            payload.reply_subject
            if payload is not None and payload.reply_subject
            else (
                ai_draft.get("subject")
                or (task.title if task.title.lower().startswith("re:") else f"Re: {task.title}")
            )
        )
        reply_body = (
            payload.reply_body
            if payload is not None and payload.reply_body
            else (ai_draft.get("body") or "")
        )
        try:
            reply_result = google_actions_service.send_gmail_reply(
                db,
                current_session.user_id,
                to_email=str(reply_to),
                subject=str(reply_subject),
                body=str(reply_body),
                thread_id=raw.get("gmail_thread_id"),
                in_reply_to=raw.get("message_id_header"),
                references=raw.get("message_id_header"),
            )
            execution_log["reply"] = reply_result
            completed_steps.append(f"Reply sent to {reply_result['to']}")
        except ScopeUpgradeRequiredError as exc:
            raise auth_error(403, "scope_upgrade_required", str(exc)) from exc
        except GoogleTokenExpiredError as exc:
            raise auth_error(403, "google_token_expired", str(exc)) from exc
        except GoogleActionError as exc:
            raise auth_error(400, "reply_action_failed", str(exc)) from exc

    # 4. Mark the original Gmail message as read and move it out of Inbox to processed folder
    if do_archive:
        target_folder = (
            (payload.target_folder if payload is not None and payload.target_folder else None)
            or ai.get("target_folder")
            or get_processed_folder_name()
        )
        try:
            archive_result = google_actions_service.mark_read_and_move_to_folder(
                db,
                current_session.user_id,
                message_id=gmail_msg_id,
                folder_name=str(target_folder),
            )
            execution_log["gmail_archive"] = archive_result
            if archive_result.get("processed"):
                completed_steps.append(f"Marked read & moved to {archive_result['folder']}")
        except ScopeUpgradeRequiredError as exc:
            raise auth_error(403, "scope_upgrade_required", str(exc)) from exc
        except GoogleTokenExpiredError as exc:
            raise auth_error(403, "google_token_expired", str(exc)) from exc
        except GoogleActionError as exc:
            raise auth_error(502, "gmail_archive_failed", str(exc)) from exc

    now = utc_now()
    if execution_log:
        raw["execution_log"] = execution_log
        task.raw_data = raw
        flag_modified(task, "raw_data")

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

    summary_message = (
        "; ".join(completed_steps) + "."
        if completed_steps
        else "Task approved successfully"
    )

    return {
        "task_id": task.id,
        "status": task.status,
        "approved_at": _format_utc(task.approved_at),
        "approved_by_user": bool(task.approved_by_user),
        "execution_log": execution_log,
        "task": _serialize_task(task),
        "message": summary_message,
    }


@router.post("/{task_id}/reject")
def reject_task(
    task_id: str,
    payload: Optional[RejectTaskRequest] = None,
    current_session: UserSession = Depends(get_current_session),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    """Idempotently reject a task and mark its Gmail email read & moved to the processed folder."""
    task = _get_owned_task_or_error(db, task_id, current_session.user_id)
    cleaned_reason = (
        payload.reason.strip() if payload and payload.reason and payload.reason.strip() else None
    )

    raw = dict(task.raw_data) if isinstance(task.raw_data, dict) else {}
    execution_log: Dict[str, Any] = dict(raw.get("execution_log") or {})
    archive_note = ""

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

        # Once acted upon (rejected), mark the inbox email read and move it to the processed folder.
        should_archive = payload.mark_read_and_move if payload is not None else True
        gmail_msg_id = str(raw.get("gmail_message_id") or task.external_message_id or "").strip()
        token_record = google_actions_service.get_token_record(db, current_session.user_id)
        if should_archive and gmail_msg_id and token_record is not None:
            ai = raw.get("ai_analysis") if isinstance(raw.get("ai_analysis"), dict) else {}
            target_folder = (
                (payload.target_folder if payload is not None and payload.target_folder else None)
                or ai.get("target_folder")
                or get_processed_folder_name()
            )
            if token_record.has_gmail_modify():
                try:
                    archive_result = google_actions_service.mark_read_and_move_to_folder(
                        db,
                        current_session.user_id,
                        message_id=gmail_msg_id,
                        folder_name=str(target_folder),
                    )
                    execution_log["gmail_archive"] = archive_result
                    raw["execution_log"] = execution_log
                    task.raw_data = raw
                    flag_modified(task, "raw_data")
                    if archive_result.get("processed"):
                        archive_note = f" Marked read & moved to {archive_result['folder']}."
                except (GoogleActionError, GoogleTokenExpiredError) as exc:
                    execution_log["gmail_archive"] = {"processed": False, "reason": str(exc)}
                    raw["execution_log"] = execution_log
                    task.raw_data = raw
                    flag_modified(task, "raw_data")
            else:
                execution_log["gmail_archive"] = {
                    "processed": False,
                    "reason": "Reconnect Google to grant Gmail modify permission for folder archiving.",
                }
                raw["execution_log"] = execution_log
                task.raw_data = raw
                flag_modified(task, "raw_data")
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
        "execution_log": execution_log,
        "task": _serialize_task(task),
        "message": f"Task rejected successfully.{archive_note}".strip(),
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
