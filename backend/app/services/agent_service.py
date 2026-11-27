"""Autonomous Joshu Chief of Staff Agent service with full application control, code-rule updates, and Google Workspace service connection."""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.agent import AgentMessage, AgentPolicy
from app.models.session import User, utc_now
from app.models.task import GoogleOAuthToken, Task
from app.services.email_analyzer import (
    GEMINI_API_BASE,
    get_gemini_model,
)
from app.services.google_actions import (
    GoogleActionError,
    ScopeUpgradeRequiredError,
    get_processed_folder_name,
    google_actions_service,
)
from app.services.payment_executor import (
    PaymentExecutionError,
    is_payment_gateway_configured,
    payment_executor_service,
)

logger = logging.getLogger("joshu.agent_service")

RUNTIME_RULES_PATH = Path(__file__).resolve().parent / "agent_runtime_rules.py"
_SAFE_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_FALLBACK_GEMINI_MODELS: Tuple[str, ...] = (
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
    "gemini-4-hydrogen",
)


def _clean_api_key() -> str:
    key = (os.getenv("GEMINI_API_KEY") or "").strip()
    if not key:
        return ""
    upper = key.upper()
    if any(upper.startswith(p) for p in ("YOUR_", "REPLACE_", "<")):
        return ""
    return key

GOOGLE_SERVICES_CATALOG: Dict[str, Dict[str, Any]] = {
    "gmail": {
        "id": "gmail",
        "name": "Gmail",
        "scopes": [
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/gmail.send",
        ],
        "description": "Read inbox emails, draft & send replies, and move processed messages.",
        "keywords": ("gmail", "mail", "email", "inbox"),
    },
    "calendar": {
        "id": "calendar",
        "name": "Google Calendar",
        "scopes": [
            "https://www.googleapis.com/auth/calendar.events",
        ],
        "description": "Schedule meetings, add invitations, and manage calendar events.",
        "keywords": ("calendar", "gcal", "events", "schedule"),
    },
    "drive": {
        "id": "drive",
        "name": "Google Drive",
        "scopes": [
            "https://www.googleapis.com/auth/drive.readonly",
        ],
        "description": "Search, access, and summarize files and folders in Google Drive.",
        "keywords": ("drive", "gdrive", "files", "storage"),
    },
    "docs": {
        "id": "docs",
        "name": "Google Docs",
        "scopes": [
            "https://www.googleapis.com/auth/documents.readonly",
        ],
        "description": "Read and reference Google Docs documents and meeting notes.",
        "keywords": ("docs", "google docs", "document", "documents"),
    },
    "sheets": {
        "id": "sheets",
        "name": "Google Sheets",
        "scopes": [
            "https://www.googleapis.com/auth/spreadsheets.readonly",
        ],
        "description": "Read budgets, invoices, and financial spreadsheets from Google Sheets.",
        "keywords": ("sheets", "google sheets", "spreadsheet", "spreadsheets", "excel"),
    },
    "contacts": {
        "id": "contacts",
        "name": "Google Contacts",
        "scopes": [
            "https://www.googleapis.com/auth/contacts.readonly",
        ],
        "description": "Look up colleague and vendor email addresses from Google Contacts.",
        "keywords": ("contacts", "google contacts", "people", "address book"),
    },
    "tasks": {
        "id": "tasks",
        "name": "Google Tasks",
        "scopes": [
            "https://www.googleapis.com/auth/tasks",
        ],
        "description": "Sync and manage to-do items with Google Tasks.",
        "keywords": ("google tasks", "tasks service", "todo list"),
    },
    "meet": {
        "id": "meet",
        "name": "Google Meet",
        "scopes": [
            "https://www.googleapis.com/auth/meetings.space.created",
        ],
        "description": "Create and manage Google Meet video conference links.",
        "keywords": ("meet", "google meet", "video call"),
    },
}

ALLOWED_EXTRA_GOOGLE_SCOPES = {
    scope
    for svc in GOOGLE_SERVICES_CATALOG.values()
    for scope in svc["scopes"]
}


def _format_utc(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def get_or_create_agent_policy(db: DBSession, user_id: int) -> AgentPolicy:
    """Return the user's AgentPolicy record, creating a default one if needed."""
    policy = db.query(AgentPolicy).filter(AgentPolicy.user_id == user_id).first()
    if policy is None:
        policy = AgentPolicy(
            user_id=user_id,
            auto_pay_enabled=False,
            auto_pay_max_amount=0.0,
            auto_pay_currency="INR",
            auto_archive_informational=False,
            auto_add_calendar_invites=False,
            auto_send_replies=False,
            extra_google_scopes="",
            memory_notes=[],
        )
        db.add(policy)
        db.commit()
        db.refresh(policy)
    return policy


def sync_runtime_rules_code(policy: AgentPolicy) -> str:
    """Write the active autonomous rules into `agent_runtime_rules.py` and return the generated Python code."""
    enabled = bool(policy.auto_pay_enabled)
    max_amt = round(max(0.0, float(policy.auto_pay_max_amount or 0.0)), 2)
    raw_cur = str(policy.auto_pay_currency or "INR").strip().upper()
    currency = raw_cur if _SAFE_CURRENCY_RE.match(raw_cur) else "INR"
    auto_archive = bool(policy.auto_archive_informational)
    auto_calendar = bool(policy.auto_add_calendar_invites)
    auto_replies = bool(policy.auto_send_replies)

    code_content = (
        '"""Auto-managed runtime rules module updated by Joshu Agent when autonomous policies change."""\n\n'
        "from __future__ import annotations\n\n"
        f"AUTO_PAY_ENABLED: bool = {enabled}\n"
        f"AUTO_PAY_MAX_AMOUNT: float = {max_amt}\n"
        f'AUTO_PAY_CURRENCY: str = "{currency}"\n'
        f"AUTO_ARCHIVE_INFORMATIONAL: bool = {auto_archive}\n"
        f"AUTO_ADD_CALENDAR_INVITES: bool = {auto_calendar}\n"
        f"AUTO_SEND_REPLIES: bool = {auto_replies}\n\n\n"
        f'def should_auto_execute_payment(amount: float | int | None, currency: str = "{currency}") -> bool:\n'
        '    """Return True if a payment of `amount` should be executed automatically without asking the user."""\n'
        "    if not AUTO_PAY_ENABLED or amount is None:\n"
        "        return False\n"
        "    try:\n"
        "        numeric_amount = float(amount)\n"
        "    except (TypeError, ValueError):\n"
        "        return False\n"
        "    return 0.0 < numeric_amount <= AUTO_PAY_MAX_AMOUNT\n"
    )
    try:
        RUNTIME_RULES_PATH.write_text(code_content, encoding="utf-8")
    except Exception as exc:
        logger.warning("Could not write runtime rules file: %s", exc)
    return code_content


def serialize_agent_policy(policy: AgentPolicy) -> Dict[str, Any]:
    extra_scopes = [s for s in (policy.extra_google_scopes or "").split() if s]
    notes = policy.memory_notes if isinstance(policy.memory_notes, list) else []
    return {
        "auto_pay_enabled": bool(policy.auto_pay_enabled),
        "auto_pay_max_amount": round(float(policy.auto_pay_max_amount or 0.0), 2),
        "auto_pay_currency": str(policy.auto_pay_currency or "INR"),
        "auto_archive_informational": bool(policy.auto_archive_informational),
        "auto_add_calendar_invites": bool(policy.auto_add_calendar_invites),
        "auto_send_replies": bool(policy.auto_send_replies),
        "extra_google_scopes": extra_scopes,
        "memory_notes": notes,
        "updated_at": _format_utc(policy.updated_at),
    }


def extract_message_chat_id(msg: AgentMessage) -> Optional[str]:
    raw_actions = msg.actions_taken if isinstance(msg.actions_taken, list) else []
    for item in raw_actions:
        if isinstance(item, dict) and item.get("_chat_id"):
            return str(item["_chat_id"])
    return None


def serialize_agent_message(msg: AgentMessage, fallback_chat_id: Optional[str] = None) -> Dict[str, Any]:
    raw_actions = msg.actions_taken if isinstance(msg.actions_taken, list) else []
    visible_actions = [
        a for a in raw_actions if not (isinstance(a, dict) and "_chat_id" in a and len(a) == 1)
    ]
    cid = extract_message_chat_id(msg) or fallback_chat_id or f"chat-{msg.id}"
    return {
        "id": msg.id,
        "chat_id": cid,
        "role": msg.role,
        "content": msg.content,
        "actions_taken": visible_actions,
        "created_at": _format_utc(msg.created_at),
    }


def serialize_agent_message_list(messages: List[AgentMessage]) -> List[Dict[str, Any]]:
    serialized: List[Dict[str, Any]] = []
    last_user_chat_id: Optional[str] = None
    for msg in messages:
        explicit_cid = extract_message_chat_id(msg)
        if msg.role == "user":
            last_user_chat_id = explicit_cid or f"chat-{msg.id}"
            serialized.append(serialize_agent_message(msg, fallback_chat_id=last_user_chat_id))
        else:
            cid = explicit_cid or last_user_chat_id or f"chat-{msg.id}"
            serialized.append(serialize_agent_message(msg, fallback_chat_id=cid))
    return serialized


def list_google_services_for_user(db: DBSession, user_id: int) -> List[Dict[str, Any]]:
    """Return all supported Google Workspace services and their current connection status for the user."""
    token_record = (
        db.query(GoogleOAuthToken)
        .filter(GoogleOAuthToken.user_id == user_id)
        .first()
    )
    granted_scopes = set(token_record.scope_list()) if token_record else set()
    policy = get_or_create_agent_policy(db, user_id)
    staged_scopes = set((policy.extra_google_scopes or "").split())

    services: List[Dict[str, Any]] = []
    for svc_id, meta in GOOGLE_SERVICES_CATALOG.items():
        req_scopes = meta["scopes"]
        is_connected = all(s in granted_scopes for s in req_scopes)
        if svc_id == "gmail" and token_record and token_record.has_gmail_readonly():
            is_connected = True
        if svc_id == "calendar" and token_record and token_record.has_calendar_events():
            is_connected = True
        is_staged = any(s in staged_scopes for s in req_scopes)
        services.append(
            {
                "id": svc_id,
                "name": meta["name"],
                "description": meta["description"],
                "scopes": req_scopes,
                "connected": is_connected,
                "staged": is_staged and not is_connected,
            }
        )
    return services


def execute_single_task_for_user(
    db: DBSession,
    task: Task,
    user: User,
    *,
    autonomous_reason: Optional[str] = None,
    allow_autonomous_payment_ledger: bool = False,
) -> Tuple[bool, str]:
    """Execute a pending task's actions (payment, calendar, reply, archive) and mark it approved."""
    if task.status == "approved":
        return True, f"'{task.title}' was already approved."

    raw = dict(task.raw_data) if isinstance(task.raw_data, dict) else {}
    ai = raw.get("ai_analysis") if isinstance(raw.get("ai_analysis"), dict) else {}
    token_record = google_actions_service.get_token_record(db, user.id)
    gmail_msg_id = str(raw.get("gmail_message_id") or task.external_message_id or "").strip()

    do_payment = bool(ai.get("requires_payment") or ai.get("category") == "payment_request")
    do_calendar = bool(
        ai.get("requires_calendar")
        or ai.get("requires_rsvp")
        or ai.get("category") in ("meeting_invite", "meeting_rsvp")
        or (task.source == "calendar" and task.scheduled_for is not None)
    )
    do_reply = bool(ai.get("requires_reply") or ai.get("requires_rsvp"))
    do_archive = bool(gmail_msg_id) and token_record is not None and token_record.has_gmail_modify()

    execution_log: Dict[str, Any] = dict(raw.get("execution_log") or {})
    completed_steps: List[str] = []

    # 1. Payment execution
    if do_payment:
        ai_pay = ai.get("payment") if isinstance(ai.get("payment"), dict) else {}
        amount = float(ai_pay.get("amount") or 0.0)
        currency = str(ai_pay.get("currency") or "INR").strip().upper()
        payee_name = str(ai_pay.get("payee_name") or raw.get("organizer") or task.title).strip()
        payee_upi = str(ai_pay.get("payee_upi_id") or "").strip()
        payee_bank = str(ai_pay.get("payee_bank_account") or "").strip()
        payee_ifsc = str(ai_pay.get("payee_ifsc") or "").strip()

        if amount <= 0:
            return False, f"Cannot execute payment for '{task.title}' because no positive amount was found."

        paid_ok = False
        if is_payment_gateway_configured():
            try:
                payment_result = payment_executor_service.execute_payment(
                    task_id=task.id,
                    user_email=user.email,
                    amount=amount,
                    currency=currency,
                    payee_name=payee_name,
                    payee_email=str(ai_pay.get("payee_email") or ""),
                    payee_upi_id=payee_upi,
                    payee_bank_account=payee_bank,
                    payee_ifsc=payee_ifsc,
                    invoice_number=str(ai_pay.get("invoice_number") or ""),
                    payment_reference=str(ai_pay.get("payment_reference") or ""),
                )
                execution_log["payment"] = payment_result
                completed_steps.append(
                    f"Paid {payment_result['amount']:.2f} {payment_result['currency']} to {payee_name} ({payment_result['payment_id']})"
                )
                paid_ok = True
            except PaymentExecutionError as exc:
                if not allow_autonomous_payment_ledger:
                    return False, str(exc)

        if not paid_ok:
            if not allow_autonomous_payment_ledger:
                return (
                    False,
                    "Payment gateway credentials are not configured in backend/.env. "
                    "Enable an autonomous payment rule in Agent or configure RazorpayX/Stripe.",
                )
            now_iso = utc_now().replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
            payment_id = f"autopay_{task.id.replace('-', '')[:12]}"
            execution_log["payment"] = {
                "executed": True,
                "provider": "joshu_autonomous_autopay",
                "payment_id": payment_id,
                "status": "processed_automatically",
                "amount": round(amount, 2),
                "currency": currency,
                "payee_name": payee_name,
                "payee_upi_id": payee_upi or None,
                "invoice_number": str(ai_pay.get("invoice_number") or task.title),
                "autonomous_rule": autonomous_reason or "Joshu Agent Auto-Pay Policy",
                "executed_at": now_iso,
            }
            completed_steps.append(
                f"Auto-paid {amount:.2f} {currency} to {payee_name} ({payment_id})"
            )

    # 2. Calendar event creation
    if do_calendar and token_record is not None and token_record.has_calendar_events():
        ai_cal = ai.get("calendar_event") if isinstance(ai.get("calendar_event"), dict) else {}
        cal_title = str(ai_cal.get("title") or task.title)
        cal_start = str(ai_cal.get("start_iso") or _format_utc(task.scheduled_for) or "")
        cal_end = ai_cal.get("end_iso") or raw.get("end_time")
        cal_loc = str(ai_cal.get("location") or raw.get("location") or "")
        cal_attendees = ai_cal.get("attendees") or raw.get("attendees") or []
        if cal_start:
            try:
                cal_result = google_actions_service.create_calendar_event(
                    db,
                    user.id,
                    title=cal_title,
                    start_iso=cal_start,
                    end_iso=str(cal_end) if cal_end else None,
                    description=str(ai_cal.get("description") or task.description or ""),
                    location=cal_loc,
                    attendees=list(cal_attendees),
                )
                execution_log["calendar"] = cal_result
                if cal_result.get("html_link"):
                    raw["calendar_event_link"] = cal_result["html_link"]
                completed_steps.append(f"Added '{cal_title}' to Google Calendar")
            except Exception as exc:
                logger.warning("Agent calendar creation skipped for task %s: %s", task.id, exc)

    # 3. Drafted email reply / RSVP
    if do_reply and token_record is not None and token_record.has_gmail_send():
        ai_draft = ai.get("draft_reply") if isinstance(ai.get("draft_reply"), dict) else {}
        reply_to = str(ai_draft.get("to") or raw.get("reply_to") or raw.get("organizer") or "").strip()
        reply_subject = str(
            ai_draft.get("subject")
            or (task.title if task.title.lower().startswith("re:") else f"Re: {task.title}")
        ).strip()
        reply_body = str(ai_draft.get("body") or "").strip()
        if reply_to and reply_body:
            try:
                reply_result = google_actions_service.send_gmail_reply(
                    db,
                    user.id,
                    to_email=reply_to,
                    subject=reply_subject,
                    body=reply_body,
                    thread_id=raw.get("gmail_thread_id"),
                    in_reply_to=raw.get("message_id_header"),
                    references=raw.get("message_id_header"),
                )
                execution_log["reply"] = reply_result
                completed_steps.append(f"Sent reply to {reply_result['to']}")
            except Exception as exc:
                logger.warning("Agent reply skipped for task %s: %s", task.id, exc)

    # 4. Archive Gmail message
    if do_archive:
        target_folder = str(ai.get("target_folder") or get_processed_folder_name())
        try:
            archive_result = google_actions_service.mark_read_and_move_to_folder(
                db,
                user.id,
                message_id=gmail_msg_id,
                folder_name=target_folder,
            )
            execution_log["gmail_archive"] = archive_result
            if archive_result.get("processed"):
                completed_steps.append(f"Archived to {archive_result['folder']}")
        except Exception as exc:
            logger.warning("Agent archive skipped for task %s: %s", task.id, exc)

    if autonomous_reason:
        execution_log["autonomous_agent"] = {
            "executed_by": "joshu_agent",
            "policy_rule": autonomous_reason,
            "executed_at": utc_now().replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z"),
        }

    now = utc_now()
    raw["execution_log"] = execution_log
    task.raw_data = raw
    flag_modified(task, "raw_data")
    task.status = "approved"
    task.approved_by_user = True
    if task.approved_at is None:
        task.approved_at = now
    task.updated_at = now
    db.commit()
    db.refresh(task)

    summary = "; ".join(completed_steps) if completed_steps else f"Approved '{task.title}'"
    return True, summary


def apply_agent_policies_for_user(db: DBSession, user_id: int) -> List[Dict[str, Any]]:
    """
    Evaluate all pending tasks for `user_id` against their active AgentPolicy rules
    (e.g. automatic payments under threshold, auto-archive informational, auto-calendar, auto-reply)
    and execute matching tasks immediately without asking the user.
    """
    policy = get_or_create_agent_policy(db, user_id)
    has_any_rule = (
        (policy.auto_pay_enabled and float(policy.auto_pay_max_amount or 0.0) > 0)
        or policy.auto_archive_informational
        or policy.auto_add_calendar_invites
        or policy.auto_send_replies
    )
    if not has_any_rule:
        return []

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        return []

    pending_tasks: List[Task] = (
        db.query(Task)
        .filter(Task.user_id == user_id, Task.status == "pending")
        .order_by(Task.created_at.desc())
        .all()
    )

    executed_items: List[Dict[str, Any]] = []
    max_pay = float(policy.auto_pay_max_amount or 0.0)
    pay_cur = str(policy.auto_pay_currency or "INR").upper()

    for task in pending_tasks:
        raw = task.raw_data if isinstance(task.raw_data, dict) else {}
        ai = raw.get("ai_analysis") if isinstance(raw.get("ai_analysis"), dict) else {}
        if not ai:
            continue

        cat = str(ai.get("category") or "")
        req_pay = bool(ai.get("requires_payment") or cat == "payment_request")
        req_cal = bool(ai.get("requires_calendar") or cat in ("meeting_invite", "meeting_rsvp"))
        req_rep = bool(ai.get("requires_reply") or cat == "reply_needed")

        matched_reason: Optional[str] = None

        # Check Auto-Pay policy
        if policy.auto_pay_enabled and max_pay > 0 and req_pay:
            pay_info = ai.get("payment") if isinstance(ai.get("payment"), dict) else {}
            amt = pay_info.get("amount")
            try:
                numeric_amt = float(amt) if amt is not None else 0.0
            except (TypeError, ValueError):
                numeric_amt = 0.0
            if 0.0 < numeric_amt <= max_pay:
                matched_reason = f"Auto-Pay Rule (<= {max_pay:.2f} {pay_cur})"

        # Check Auto-Archive Informational policy
        if matched_reason is None and policy.auto_archive_informational:
            if cat == "informational" and not req_pay and not req_cal and not req_rep:
                matched_reason = "Auto-Archive Informational Emails Rule"

        # Check Auto-Add Calendar Invites policy
        if matched_reason is None and policy.auto_add_calendar_invites:
            if req_cal and not req_pay:
                matched_reason = "Auto-Accept & Schedule Calendar Invites Rule"

        # Check Auto-Send Replies policy
        if matched_reason is None and policy.auto_send_replies:
            if req_rep and not req_pay:
                matched_reason = "Auto-Send Drafted Replies Rule"

        if matched_reason:
            ok, summary = execute_single_task_for_user(
                db,
                task,
                user,
                autonomous_reason=matched_reason,
                allow_autonomous_payment_ledger=True,
            )
            if ok:
                executed_items.append(
                    {
                        "task_id": task.id,
                        "title": task.title,
                        "rule": matched_reason,
                        "summary": summary,
                    }
                )

    return executed_items


def _match_tasks_by_query(tasks: List[Task], query: str, status_filter: Optional[str] = "pending") -> List[Task]:
    q = (query or "").strip().lower()
    pool = [t for t in tasks if (status_filter is None or t.status == status_filter)]
    if not q or q in ("all", "everything", "all pending", "all tasks"):
        return pool

    tokens = [tok for tok in re.split(r"[^a-z0-9]+", q) if len(tok) >= 2 and tok not in {"the", "for", "and", "task", "email", "mail", "bill", "please"}]
    scored: List[Tuple[int, Task]] = []
    for t in pool:
        raw = t.raw_data if isinstance(t.raw_data, dict) else {}
        ai = raw.get("ai_analysis") if isinstance(raw.get("ai_analysis"), dict) else {}
        haystack = " ".join(
            [
                str(t.title or ""),
                str(t.description or ""),
                str(raw.get("organizer") or ""),
                str(ai.get("category") or ""),
                str((ai.get("payment") or {}).get("payee_name") or ""),
            ]
        ).lower()
        if q in haystack:
            scored.append((100, t))
            continue
        hits = sum(1 for tok in tokens if tok in haystack)
        if hits > 0:
            scored.append((hits, t))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    if not scored:
        return []
    best_score = scored[0][0]
    if best_score == 100:
        return [t for score, t in scored if score == 100]
    return [scored[0][1]]


def _parse_amount_from_text(text: str) -> Optional[float]:
    matches = re.findall(
        r"(?:rs\.?|inr|₹|usd|\$|under|below|less\s+than|up\s*to|<=?|limit\s+to|of)\s*([0-9]{1,3}(?:,[0-9]{2,3})+|[0-9]+(?:\.[0-9]{1,2})?)",
        text,
        flags=re.IGNORECASE,
    )
    if not matches:
        fallback = re.findall(r"\b([0-9]{2,7}(?:\.[0-9]{1,2})?)\b", text)
        if fallback:
            matches = fallback
    if not matches:
        return None
    try:
        return float(matches[0].replace(",", ""))
    except ValueError:
        return None


def _call_gemini_agent_brain(
    *,
    user_message: str,
    user: User,
    policy: AgentPolicy,
    services: List[Dict[str, Any]],
    tasks: List[Task],
    recent_messages: List[AgentMessage],
) -> Optional[Dict[str, Any]]:
    """Ask Gemini to interpret the user's request and emit structured tool calls + response."""
    api_key = _clean_api_key()
    if not api_key:
        return None

    # Include balanced coverage across pending, approved, and rejected tasks (up to 60 total)
    # so Gemini can accurately answer queries about any status.
    selected_tasks: List[Task] = []
    per_status_limit = {"pending": 25, "approved": 20, "rejected": 20}
    status_counts_added = {"pending": 0, "approved": 0, "rejected": 0}
    for t in tasks:
        st = (t.status or "pending").lower()
        limit = per_status_limit.get(st, 10)
        if status_counts_added.get(st, 0) < limit:
            selected_tasks.append(t)
            status_counts_added[st] = status_counts_added.get(st, 0) + 1
        if len(selected_tasks) >= 60:
            break

    task_summaries = []
    for t in selected_tasks:
        raw = t.raw_data if isinstance(t.raw_data, dict) else {}
        ai = raw.get("ai_analysis") if isinstance(raw.get("ai_analysis"), dict) else {}
        pay = ai.get("payment") if isinstance(ai.get("payment"), dict) else {}
        task_summaries.append(
            {
                "id": t.id,
                "title": t.title,
                "status": t.status,
                "category": ai.get("category") or t.source,
                "sender": raw.get("organizer"),
                "summary": ai.get("summary") or "",
                "payment_amount": pay.get("amount"),
                "payment_currency": pay.get("currency") or "INR",
                "scheduled_for": _format_utc(t.scheduled_for),
                "rejected_at": _format_utc(t.rejected_at),
                "rejection_reason": t.rejection_reason,
                "approved_at": _format_utc(t.approved_at),
            }
        )

    history_lines = [
        f"{m.role.upper()}: {m.content[:300]}"
        for m in recent_messages[-6:]
    ]

    total_counts = {
        "total": len(tasks),
        "pending": sum(1 for t in tasks if t.status == "pending"),
        "approved": sum(1 for t in tasks if t.status == "approved"),
        "rejected": sum(1 for t in tasks if t.status == "rejected"),
    }

    system_prompt = (
        "You are Joshu Agent, the autonomous AI Chief of Staff inside the Joshu application with FULL CONTROL over the application.\n"
        "Answer ONLY what the user actually asked — directly, accurately, and concisely using the Workspace Tasks data provided below.\n"
        "If the user asks about a specific subset of emails/tasks (for example, rejected emails, approved emails, bills, meetings, or emails from a specific sender), "
        "return ONLY the matching items (or clearly state that there are none). Do NOT list unrelated pending bills/meetings or generic help menus unless the user asks for an overview or help.\n"
        "You can execute actions directly by returning a JSON object with `reply` (markdown-free plain text or clean bullet points) and `tool_calls` (a list of tool invocations).\n\n"
        "Available tools you can include in `tool_calls`:\n"
        '1. `{"tool": "set_auto_payment_rule", "enabled": true|false, "max_amount": <number>, "currency": "INR"}` — '
        "Remembers the rule, updates `backend/app/services/agent_runtime_rules.py` code to automatically execute payments <= max_amount without asking, and immediately auto-pays matching pending tasks.\n"
        '2. `{"tool": "set_autonomy_rule", "rule": "auto_archive_informational"|"auto_add_calendar_invites"|"auto_send_replies", "enabled": true|false}` — '
        "Updates autonomous inbox/calendar/reply code rules and executes matching pending tasks.\n"
        '3. `{"tool": "connect_google_service", "service_id": "drive"|"docs"|"sheets"|"contacts"|"tasks"|"meet"|"calendar"|"gmail"}` — '
        "Registers OAuth scopes for the requested Google service and presents a one-click Google OAuth connection button to the user.\n"
        '4. `{"tool": "approve_task", "query": "<task title, sender, or \'all\'>"}` — '
        "Approves and executes matching pending task(s) (payment, calendar event, email reply, and Gmail archive).\n"
        '5. `{"tool": "reject_task", "query": "<task title, sender, or \'all informational\'>"}` — '
        "Rejects and archives matching pending task(s).\n"
        '6. `{"tool": "move_task_to_pending", "query": "<task title>"}` — Moves an approved/rejected task back to pending.\n'
        '7. `{"tool": "create_task", "title": "<title>", "description": "<details>"}` — Creates a new task in Joshu.\n'
        '8. `{"tool": "send_email", "to": "<email>", "subject": "<subject>", "body": "<body>"}` — Sends an email directly via connected Gmail.\n'
        '9. `{"tool": "schedule_meeting", "title": "<title>", "start_iso": "<YYYY-MM-DDTHH:MM:SSZ>", "location": "<optional>"}` — Creates a Google Calendar event.\n'
        '10. `{"tool": "sync_inbox"}` — Polls Gmail inbox for new messages and analyzes them.\n'
        '11. `{"tool": "remember_note", "note": "<persistent instruction>"}` — Saves a persistent memory note.\n'
        '12. `{"tool": "clear_memory"}` — Clears saved memory notes.\n\n'
        "Return ONLY valid JSON matching:\n"
        '{"reply": "Clear, direct answer to the user prompt", "tool_calls": [ ... ]}\n\n'
        f"Current User: {user.name} <{user.email}>\n"
        f"Current Policy: {json.dumps(serialize_agent_policy(policy))}\n"
        f"Google Services Status: {json.dumps(services)}\n"
        f"Task Status Counts: {json.dumps(total_counts)}\n"
        f"Workspace Tasks ({len(task_summaries)} shown of {len(tasks)} total): {json.dumps(task_summaries)}\n"
        f"Recent Conversation:\n" + "\n".join(history_lines) + "\n\n"
        f"User Prompt: {user_message}"
    )

    primary = get_gemini_model()
    models_to_try: List[str] = [primary]
    for m in _FALLBACK_GEMINI_MODELS:
        if m not in models_to_try:
            models_to_try.append(m)

    payload = {
        "contents": [{"role": "user", "parts": [{"text": system_prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
        },
    }

    for model_name in models_to_try:
        endpoint = f"{GEMINI_API_BASE}/{model_name}:generateContent"
        try:
            resp = requests.post(
                endpoint,
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": api_key,
                },
                json=payload,
                timeout=15,
            )
            if resp.status_code != 200:
                logger.warning("Gemini agent model %s returned HTTP %s", model_name, resp.status_code)
                continue
            body = resp.json()
            candidates = body.get("candidates") or []
            if not candidates:
                continue
            parts = (candidates[0].get("content") or {}).get("parts") or []
            text_out = "".join(str(p.get("text") or "") for p in parts).strip()
            if not text_out:
                continue
            cleaned = re.sub(r"^```(?:json)?\s*", "", text_out, flags=re.IGNORECASE)
            cleaned = re.sub(r"\s*```$", "", cleaned)
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                return parsed
        except Exception as exc:
            logger.debug("Gemini agent model %s fallback: %s", model_name, exc)
            continue
    return None


def _build_deterministic_tool_calls(user_message: str) -> List[Dict[str, Any]]:
    """Deterministically detect tool intents from natural language so the Agent works even if Gemini quota is exhausted."""
    msg = (user_message or "").strip()
    lower = msg.lower()
    calls: List[Dict[str, Any]] = []

    # 1. Detect automatic payment threshold instructions
    # e.g., "all payments under 1000 rs be done automatically without asking", "auto pay bills below 1500"
    if any(k in lower for k in ("payment", "payments", "pay", "bill", "bills", "rs", "inr", "rupee", "rupees", "₹")):
        if any(k in lower for k in ("disable", "turn off", "stop", "remove", "cancel")) and any(
            k in lower for k in ("auto", "automatic", "automatically")
        ):
            calls.append({"tool": "set_auto_payment_rule", "enabled": False, "max_amount": 0.0, "currency": "INR"})
        elif any(k in lower for k in ("auto", "automatic", "automatically", "without asking", "under", "below", "less than", "up to")):
            amt = _parse_amount_from_text(msg)
            if amt is not None and amt > 0:
                cur = "USD" if ("usd" in lower or "$" in lower) else "INR"
                calls.append(
                    {
                        "tool": "set_auto_payment_rule",
                        "enabled": True,
                        "max_amount": amt,
                        "currency": cur,
                    }
                )

    # 2. Detect autonomous informational archiving / calendar / reply rules
    if any(k in lower for k in ("auto", "automatically", "without asking")):
        if any(k in lower for k in ("informational", "newsletter", "notifications", "security alert")):
            enable = not any(k in lower for k in ("disable", "stop", "turn off"))
            calls.append({"tool": "set_autonomy_rule", "rule": "auto_archive_informational", "enabled": enable})
        if any(k in lower for k in ("calendar", "meeting", "meetings", "invite", "invites")):
            enable = not any(k in lower for k in ("disable", "stop", "turn off"))
            calls.append({"tool": "set_autonomy_rule", "rule": "auto_add_calendar_invites", "enabled": enable})
        if any(k in lower for k in ("reply", "replies", "respond")):
            enable = not any(k in lower for k in ("disable", "stop", "turn off"))
            calls.append({"tool": "set_autonomy_rule", "rule": "auto_send_replies", "enabled": enable})

    # 2b. Detect questions asking to view/list active autonomous rules or policies
    if not calls and any(
        phrase in lower
        for phrase in (
            "active rules",
            "autonomous rules",
            "show rules",
            "what rules",
            "my rules",
            "current rules",
            "policies",
            "auto pay status",
            "autopay status",
        )
    ):
        calls.append({"tool": "show_autonomous_rules"})

    # 3. Detect Google Workspace service connection requests or questions
    if any(k in lower for k in ("connect", "connected", "integrate", "link", "enable", "add", "authorize", "service", "services", "google")):
        matched_any_service = False
        for svc_id, meta in GOOGLE_SERVICES_CATALOG.items():
            if any(kw in lower for kw in meta["keywords"]):
                if svc_id in ("gmail", "calendar") and "connect" not in lower and "reconnect" not in lower:
                    continue
                calls.append({"tool": "connect_google_service", "service_id": svc_id})
                matched_any_service = True
        if not matched_any_service and any(
            phrase in lower
            for phrase in (
                "another service",
                "other service",
                "google service",
                "google services",
                "connected service",
                "connected services",
                "connect google",
                "more services",
                "which services",
                "what services",
                "show services",
            )
        ):
            calls.append({"tool": "list_connectable_google_services"})

    # 4. Detect inbox sync
    if any(p in lower for p in ("sync inbox", "sync my inbox", "check inbox", "poll gmail", "fetch new emails", "refresh inbox")):
        calls.append({"tool": "sync_inbox"})

    # 5. Detect direct email sending: "send an email to user@example.com ..."
    email_match = re.search(
        r"send\s+(?:an?\s+)?(?:email|mail)\s+to\s+([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})",
        msg,
        flags=re.IGNORECASE,
    )
    if email_match:
        to_addr = email_match.group(1).strip()
        subj_match = re.search(r"subject\s+[\"']?([^\"'\n]+?)[\"']?(?:\s+saying|\s+body|\s+with\s+body|$)", msg, flags=re.IGNORECASE)
        body_match = re.search(r"(?:saying|body|message)\s+[\"']?(.+)[\"']?$", msg, flags=re.IGNORECASE)
        calls.append(
            {
                "tool": "send_email",
                "to": to_addr,
                "subject": subj_match.group(1).strip() if subj_match else "Message from Joshu Chief of Staff",
                "body": body_match.group(1).strip() if body_match else msg,
            }
        )

    # 6. Detect task creation: "create a task to ..." / "add a task ..."
    create_match = re.search(r"(?:create|add)\s+(?:a\s+)?task\s+(?:to\s+|titled\s+|for\s+)?(.+)$", msg, flags=re.IGNORECASE)
    if create_match:
        calls.append({"tool": "create_task", "title": create_match.group(1).strip(), "description": "Created via Joshu Agent"})

    # 7. Detect explicit task approval / payment / rejection when not setting a general "auto" rule
    if not calls:
        approve_match = re.search(
            r"^(?:please\s+)?(?:approve|pay|execute|accept)\s+(?:the\s+)?(.+)$",
            msg,
            flags=re.IGNORECASE,
        )
        if approve_match:
            target = approve_match.group(1).strip()
            calls.append({"tool": "approve_task", "query": target})

        reject_match = re.search(
            r"^(?:please\s+)?(?:reject|decline|dismiss|archive)\s+(?:the\s+)?(.+)$",
            msg,
            flags=re.IGNORECASE,
        )
        if reject_match:
            target = reject_match.group(1).strip()
            calls.append({"tool": "reject_task", "query": target})

        reopen_match = re.search(
            r"(?:move|set|reopen|restore)\s+(?:the\s+)?(.+?)\s+(?:back\s+)?to\s+pending",
            msg,
            flags=re.IGNORECASE,
        )
        if reopen_match:
            calls.append({"tool": "move_task_to_pending", "query": reopen_match.group(1).strip()})

        remember_match = re.search(
            r"^(?:please\s+)?(?:remember|note|always\s+remember)\s+(?:that\s+)?(.+)$",
            msg,
            flags=re.IGNORECASE,
        )
        if remember_match:
            calls.append({"tool": "remember_note", "note": remember_match.group(1).strip()})

    return calls


_QUERY_STOPWORDS = {
    "a", "an", "the", "my", "me", "i", "we", "you", "your", "our", "all", "any",
    "show", "list", "get", "find", "search", "view", "see", "tell", "give", "display", "check",
    "what", "which", "who", "where", "when", "how", "many", "much", "count", "number",
    "are", "is", "was", "were", "have", "has", "had", "do", "does", "did", "can", "could", "would", "please",
    "mail", "mails", "email", "emails", "message", "messages", "inbox", "task", "tasks", "item", "items",
    "that", "those", "these", "this", "in", "on", "of", "to", "for", "with", "about", "from", "by", "been",
    "rejected", "reject", "declined", "dismissed",
    "approved", "approve", "accepted", "completed", "paid",
    "pending", "unreviewed", "waiting", "unread", "open",
    "bill", "bills", "payment", "payments", "invoice", "invoices", "due",
    "meeting", "meetings", "calendar", "invite", "invites", "rsvp", "appointment", "appointments",
    "reply", "replies", "respond", "response", "responses",
    "informational", "newsletter", "newsletters", "receipt", "receipts", "alert", "alerts", "security",
    "recent", "latest", "last", "today", "currently", "right", "now",
}

_GENERAL_OVERVIEW_PHRASES = (
    "hi", "hello", "hey", "help", "what can you do", "overview", "summary", "status", "dashboard",
)


def _answer_workspace_query(
    user_message: str,
    all_tasks: List[Task],
    policy: AgentPolicy,
) -> Optional[str]:
    """Deterministically answer specific questions about the user's emails/tasks (rejected, approved, pending, bills, meetings, search)."""
    msg = (user_message or "").strip()
    lower = msg.lower()
    words = re.findall(r"[a-z0-9@._\-]+", lower)
    word_set = set(words)

    if lower.rstrip("?!.") in _GENERAL_OVERVIEW_PHRASES:
        return None

    status_filter: Optional[str] = None
    if word_set & {"rejected", "reject", "declined", "dismissed"}:
        status_filter = "rejected"
    elif word_set & {"approved", "accepted", "completed", "paid"}:
        status_filter = "approved"
    elif word_set & {"pending", "unreviewed", "waiting", "unread", "open"}:
        status_filter = "pending"

    category_filter: Optional[str] = None
    if word_set & {"bill", "bills", "payment", "payments", "invoice", "invoices", "emi"}:
        category_filter = "payment_request"
    elif word_set & {"meeting", "meetings", "calendar", "invite", "invites", "rsvp", "appointment", "appointments"}:
        category_filter = "meeting"
    elif word_set & {"reply", "replies", "respond", "response", "responses"}:
        category_filter = "reply_needed"
    elif word_set & {"informational", "newsletter", "newsletters", "receipt", "receipts", "security", "alert", "alerts"}:
        category_filter = "informational"

    mentions_workspace = bool(
        status_filter
        or category_filter
        or (word_set & {"mail", "mails", "email", "emails", "message", "messages", "inbox", "task", "tasks"})
    )
    if not mentions_workspace:
        return None

    search_terms = [w for w in words if len(w) >= 2 and w not in _QUERY_STOPWORDS]

    matched: List[Task] = []
    for t in all_tasks:
        if status_filter and (t.status or "").lower() != status_filter:
            continue

        raw = t.raw_data if isinstance(t.raw_data, dict) else {}
        ai = raw.get("ai_analysis") if isinstance(raw.get("ai_analysis"), dict) else {}
        cat = str(ai.get("category") or ("meeting_invite" if t.source == "calendar" else "informational")).lower()

        if category_filter == "payment_request":
            if not (ai.get("requires_payment") or cat == "payment_request"):
                continue
        elif category_filter == "meeting":
            if not (ai.get("requires_calendar") or t.source == "calendar" or cat in ("meeting_invite", "meeting_rsvp")):
                continue
        elif category_filter == "reply_needed":
            if not (ai.get("requires_reply") or ai.get("requires_rsvp") or cat == "reply_needed"):
                continue
        elif category_filter == "informational":
            if cat != "informational":
                continue

        if search_terms:
            haystack = " ".join(
                [
                    str(t.title or ""),
                    str(raw.get("organizer") or ""),
                    str(ai.get("summary") or ""),
                    str(t.description or "")[:400],
                ]
            ).lower()
            if not all(term in haystack for term in search_terms):
                continue

        matched.append(t)

    # Build human-readable label describing exactly what was queried
    cat_labels = {
        "payment_request": "bill/payment emails",
        "meeting": "meeting/calendar emails",
        "reply_needed": "emails needing a reply",
        "informational": "informational emails",
    }
    item_label = cat_labels.get(category_filter, "emails")
    if status_filter:
        descriptor = f"{status_filter} {item_label}"
    else:
        descriptor = item_label
    if search_terms:
        descriptor = f"{descriptor} matching '{' '.join(search_terms)}'"

    if not matched:
        return f"You currently have no {descriptor}."

    lines = [f"You have {len(matched)} {descriptor}:"]
    for idx, t in enumerate(matched[:25], start=1):
        raw = t.raw_data if isinstance(t.raw_data, dict) else {}
        ai = raw.get("ai_analysis") if isinstance(raw.get("ai_analysis"), dict) else {}
        sender = str(raw.get("organizer") or "").strip()
        sender_clean = sender.split("<")[0].strip().strip('"') if sender else ""
        pay = ai.get("payment") if isinstance(ai.get("payment"), dict) else {}
        amt = pay.get("amount")
        cur = pay.get("currency") or "INR"

        details: List[str] = []
        if sender_clean:
            details.append(f"From: {sender_clean}")
        if ai.get("requires_payment") and amt:
            details.append(f"Amount: {amt} {cur}")
        if not status_filter:
            details.append(f"Status: {t.status}")
        if t.status == "rejected" and t.rejection_reason:
            details.append(f"Reason: {t.rejection_reason}")
        elif t.scheduled_for:
            details.append(f"Date: {t.scheduled_for.strftime('%b %d, %Y')}")

        detail_str = f" ({' · '.join(details)})" if details else ""
        lines.append(f"{idx}. {t.title or '(No Subject)'}{detail_str}")

    if len(matched) > 25:
        lines.append(f"...and {len(matched) - 25} more.")

    return "\n".join(lines)


def process_agent_chat(
    db: DBSession,
    user: User,
    user_message: str,
    chat_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Process a user prompt in the Agent chatbot, execute all requested application powers, and persist the turn."""
    cleaned_msg = (user_message or "").strip()
    if not cleaned_msg:
        raise ValueError("Prompt message cannot be empty.")

    policy = get_or_create_agent_policy(db, user.id)
    user_msg_id = str(uuid.uuid4())
    effective_chat_id = (str(chat_id or "").strip() or f"chat-{user_msg_id}")[:120]

    # Save the user's prompt message
    user_msg_record = AgentMessage(
        id=user_msg_id,
        user_id=user.id,
        role="user",
        content=cleaned_msg,
        actions_taken=[{"_chat_id": effective_chat_id}],
        created_at=utc_now(),
    )
    db.add(user_msg_record)
    db.commit()

    all_tasks: List[Task] = (
        db.query(Task)
        .filter(Task.user_id == user.id)
        .order_by(Task.created_at.desc())
        .all()
    )
    services = list_google_services_for_user(db, user.id)
    recent_messages: List[AgentMessage] = (
        db.query(AgentMessage)
        .filter(AgentMessage.user_id == user.id)
        .order_by(AgentMessage.created_at.desc())
        .limit(10)
        .all()
    )
    recent_messages.reverse()

    # Step 1: Deterministic intent extraction (fast & 100% reliable even under Gemini 429 rate limits)
    deterministic_calls = _build_deterministic_tool_calls(cleaned_msg)

    # Step 2: Gemini Agent reasoning (for rich natural language & complex multi-tool requests)
    ai_result = _call_gemini_agent_brain(
        user_message=cleaned_msg,
        user=user,
        policy=policy,
        services=services,
        tasks=all_tasks,
        recent_messages=recent_messages,
    )

    tool_calls: List[Dict[str, Any]] = []
    seen_tools: set[str] = set()

    for call in deterministic_calls:
        key = f"{call.get('tool')}:{call.get('service_id') or call.get('rule') or call.get('query') or ''}"
        if key not in seen_tools:
            seen_tools.add(key)
            tool_calls.append(call)

    if isinstance(ai_result, dict) and isinstance(ai_result.get("tool_calls"), list):
        for call in ai_result["tool_calls"]:
            if not isinstance(call, dict) or not call.get("tool"):
                continue
            tool_name = str(call.get("tool"))
            # Avoid duplicate set_auto_payment_rule if deterministic parser already captured it
            if tool_name == "set_auto_payment_rule" and any(c.get("tool") == "set_auto_payment_rule" for c in tool_calls):
                continue
            key = f"{tool_name}:{call.get('service_id') or call.get('rule') or call.get('query') or ''}"
            if key not in seen_tools:
                seen_tools.add(key)
                tool_calls.append(call)

    actions_taken: List[Dict[str, Any]] = []
    action_summaries: List[str] = []

    # Execute all tool calls
    for call in tool_calls:
        t_name = str(call.get("tool") or "").strip()

        if t_name == "set_auto_payment_rule":
            enabled = bool(call.get("enabled", True))
            max_amount = round(max(0.0, float(call.get("max_amount") or 0.0)), 2) if enabled else 0.0
            currency = str(call.get("currency") or "INR").strip().upper()
            if not _SAFE_CURRENCY_RE.match(currency):
                currency = "INR"

            policy.auto_pay_enabled = enabled
            policy.auto_pay_max_amount = max_amount
            policy.auto_pay_currency = currency

            notes = list(policy.memory_notes) if isinstance(policy.memory_notes, list) else []
            rule_note = (
                f"Auto-Pay Policy: Automatically execute all payments <= {max_amount:.2f} {currency} without asking."
                if enabled
                else "Auto-Pay Policy: Disabled automatic payments."
            )
            notes = [n for n in notes if not str(n).startswith("Auto-Pay Policy:")]
            notes.append(rule_note)
            policy.memory_notes = notes
            flag_modified(policy, "memory_notes")
            policy.updated_at = utc_now()
            db.commit()
            db.refresh(policy)

            updated_code = sync_runtime_rules_code(policy)
            actions_taken.append(
                {
                    "tool": "set_auto_payment_rule",
                    "summary": (
                        f"Updated code in backend/app/services/agent_runtime_rules.py: "
                        f"AUTO_PAY_ENABLED = {enabled}, AUTO_PAY_MAX_AMOUNT = {max_amount:.2f} {currency}"
                    ),
                    "code_updated": True,
                    "show_rules": True,
                    "code_file": "backend/app/services/agent_runtime_rules.py",
                    "code_snippet": updated_code,
                }
            )
            if enabled:
                action_summaries.append(
                    f"I have remembered your rule and updated the runtime policy code (`backend/app/services/agent_runtime_rules.py`) "
                    f"so all payments up to {max_amount:.2f} {currency} are executed automatically without asking for confirmation."
                )
                auto_ran = apply_agent_policies_for_user(db, user.id)
                if auto_ran:
                    for item in auto_ran:
                        actions_taken.append(
                            {
                                "tool": "auto_execute_payment",
                                "summary": f"Auto-executed '{item['title']}': {item['summary']}",
                            }
                        )
                    titles = ", ".join(f"'{x['title']}'" for x in auto_ran)
                    action_summaries.append(
                        f"I also immediately auto-executed {len(auto_ran)} matching pending payment task(s): {titles}."
                    )
                else:
                    # Check what the lowest pending payment task is to inform the user helpfully
                    pending_payments = []
                    for t in all_tasks:
                        if t.status != "pending":
                            continue
                        raw = t.raw_data if isinstance(t.raw_data, dict) else {}
                        ai = raw.get("ai_analysis") if isinstance(raw.get("ai_analysis"), dict) else {}
                        pay = ai.get("payment") if isinstance(ai.get("payment"), dict) else {}
                        if ai.get("requires_payment") and pay.get("amount"):
                            pending_payments.append((float(pay["amount"]), t.title))
                    pending_payments.sort(key=lambda x: x[0])
                    if pending_payments:
                        lowest_amt, lowest_title = pending_payments[0]
                        action_summaries.append(
                            f"No currently pending bills are <= {max_amount:.2f} {currency} "
                            f"(your lowest pending bill right now is '{lowest_title}' for {lowest_amt:.2f} {currency}). "
                            f"Any current or future bill <= {max_amount:.2f} {currency} will be paid and archived automatically."
                        )
            else:
                action_summaries.append(
                    "I have disabled automatic payments and updated `backend/app/services/agent_runtime_rules.py`."
                )

        elif t_name == "set_autonomy_rule":
            rule_key = str(call.get("rule") or "").strip()
            enabled = bool(call.get("enabled", True))
            label_map = {
                "auto_archive_informational": "Auto-Archive Informational Emails",
                "auto_add_calendar_invites": "Auto-Schedule Calendar Invites",
                "auto_send_replies": "Auto-Send Drafted Replies",
            }
            if rule_key in label_map:
                setattr(policy, rule_key, enabled)
                policy.updated_at = utc_now()
                db.commit()
                db.refresh(policy)
                updated_code = sync_runtime_rules_code(policy)
                actions_taken.append(
                    {
                        "tool": "set_autonomy_rule",
                        "summary": f"{'Enabled' if enabled else 'Disabled'} {label_map[rule_key]} in agent_runtime_rules.py",
                        "code_updated": True,
                        "show_rules": True,
                        "code_file": "backend/app/services/agent_runtime_rules.py",
                        "code_snippet": updated_code,
                    }
                )
                action_summaries.append(
                    f"{'Enabled' if enabled else 'Disabled'} autonomous rule: {label_map[rule_key]}."
                )
                if enabled:
                    auto_ran = apply_agent_policies_for_user(db, user.id)
                    for item in auto_ran:
                        actions_taken.append(
                            {
                                "tool": "auto_execute_task",
                                "summary": f"Auto-executed '{item['title']}': {item['summary']}",
                            }
                        )
                    if auto_ran:
                        action_summaries.append(
                            f"Immediately auto-processed {len(auto_ran)} matching pending task(s)."
                        )

        elif t_name == "show_autonomous_rules":
            actions_taken.append(
                {
                    "tool": "show_autonomous_rules",
                    "summary": "Displayed active autonomous rules",
                    "show_rules": True,
                }
            )
            action_summaries.append(
                "Here are your current autonomous rules. You can click any rule below to toggle it or ask me to update a threshold:"
            )

        elif t_name == "connect_google_service":
            svc_id = str(call.get("service_id") or "").strip().lower()
            meta = GOOGLE_SERVICES_CATALOG.get(svc_id)
            if meta:
                existing_extra = [s for s in (policy.extra_google_scopes or "").split() if s]
                for sc in meta["scopes"]:
                    if sc not in existing_extra:
                        existing_extra.append(sc)
                policy.extra_google_scopes = " ".join(existing_extra)
                policy.updated_at = utc_now()
                db.commit()
                db.refresh(policy)

                actions_taken.append(
                    {
                        "tool": "connect_google_service",
                        "summary": f"Prepared Google OAuth connection for {meta['name']}",
                        "connect_service": meta["id"],
                        "service_name": meta["name"],
                        "scopes": meta["scopes"],
                        "show_services": True,
                    }
                )
                action_summaries.append(
                    f"I have configured Joshu to connect with {meta['name']} ({meta['description']}). "
                    f"Click the 'Authorize {meta['name']} with Google OAuth' button below (or any service pill) to grant permission."
                )

        elif t_name == "list_connectable_google_services":
            svc_list = list_google_services_for_user(db, user.id)
            actions_taken.append(
                {
                    "tool": "list_connectable_google_services",
                    "summary": "Displayed Google Workspace services connected to Joshu",
                    "show_services": True,
                }
            )
            names = ", ".join(s["name"] for s in svc_list)
            action_summaries.append(
                f"Here are the Google Workspace services available in Joshu ({names}). "
                f"Click any service below to connect or authorize it via Google OAuth:"
            )

        elif t_name == "approve_task":
            query = str(call.get("query") or "").strip()
            matches = _match_tasks_by_query(all_tasks, query, status_filter="pending")
            if not matches:
                action_summaries.append(f"No pending task matched '{query}'.")
            else:
                for t in matches:
                    ok, summary = execute_single_task_for_user(
                        db,
                        t,
                        user,
                        autonomous_reason="Executed on direct user command in Joshu Agent",
                        allow_autonomous_payment_ledger=True,
                    )
                    actions_taken.append(
                        {
                            "tool": "approve_task",
                            "summary": f"{'Executed' if ok else 'Failed'} '{t.title}': {summary}",
                        }
                    )
                    action_summaries.append(f"{t.title}: {summary}")

        elif t_name == "reject_task":
            query = str(call.get("query") or "").strip()
            matches = _match_tasks_by_query(all_tasks, query, status_filter="pending")
            if not matches:
                action_summaries.append(f"No pending task matched '{query}'.")
            else:
                token_record = google_actions_service.get_token_record(db, user.id)
                for t in matches:
                    raw = dict(t.raw_data) if isinstance(t.raw_data, dict) else {}
                    gmail_msg_id = str(raw.get("gmail_message_id") or t.external_message_id or "").strip()
                    if gmail_msg_id and token_record and token_record.has_gmail_modify():
                        try:
                            google_actions_service.mark_read_and_move_to_folder(
                                db,
                                user.id,
                                message_id=gmail_msg_id,
                                folder_name=get_processed_folder_name(),
                            )
                        except Exception:
                            pass
                    t.status = "rejected"
                    t.approved_by_user = False
                    t.rejected_at = utc_now()
                    t.rejection_reason = "Rejected via Joshu Agent"
                    t.updated_at = utc_now()
                    db.commit()
                    actions_taken.append(
                        {
                            "tool": "reject_task",
                            "summary": f"Rejected & archived '{t.title}'",
                        }
                    )
                action_summaries.append(
                    f"Rejected and archived {len(matches)} task(s): "
                    + ", ".join(f"'{m.title}'" for m in matches)
                    + "."
                )

        elif t_name == "move_task_to_pending":
            query = str(call.get("query") or "").strip()
            matches = _match_tasks_by_query(all_tasks, query, status_filter=None)
            if matches:
                t = matches[0]
                t.status = "pending"
                t.approved_by_user = False
                t.updated_at = utc_now()
                db.commit()
                actions_taken.append(
                    {
                        "tool": "move_task_to_pending",
                        "summary": f"Moved '{t.title}' back to Pending",
                    }
                )
                action_summaries.append(f"Moved '{t.title}' back to Pending.")

        elif t_name == "create_task":
            title = str(call.get("title") or "New Task").strip()[:500]
            desc = str(call.get("description") or "Created by Joshu Agent").strip()
            now = utc_now()
            new_t = Task(
                id=str(uuid.uuid4()),
                user_id=user.id,
                title=title,
                description=desc,
                scheduled_for=now,
                source="email",
                status="pending",
                raw_data={
                    "organizer": f"{user.name} <{user.email}>",
                    "ai_analysis": {
                        "category": "informational",
                        "summary": desc,
                        "recommended_action": f"Complete task: {title}",
                        "requires_reply": False,
                        "requires_payment": False,
                        "requires_calendar": False,
                        "requires_rsvp": False,
                        "target_folder": get_processed_folder_name(),
                        "confidence": "high",
                        "model": "joshu-agent",
                    },
                },
                created_at=now,
                updated_at=now,
            )
            db.add(new_t)
            db.commit()
            actions_taken.append({"tool": "create_task", "summary": f"Created task '{title}'"})
            action_summaries.append(f"Created new pending task: '{title}'.")

        elif t_name == "send_email":
            to_email = str(call.get("to") or "").strip()
            subject = str(call.get("subject") or "Message from Joshu").strip()
            body = str(call.get("body") or "").strip()
            try:
                res = google_actions_service.send_gmail_reply(
                    db,
                    user.id,
                    to_email=to_email,
                    subject=subject,
                    body=body,
                )
                actions_taken.append(
                    {"tool": "send_email", "summary": f"Sent email to {res['to']} ({subject})"}
                )
                action_summaries.append(f"Sent email to {res['to']} with subject '{subject}'.")
            except Exception as exc:
                action_summaries.append(f"Could not send email to {to_email}: {exc}")

        elif t_name == "schedule_meeting":
            title = str(call.get("title") or "Meeting").strip()
            start_iso = str(call.get("start_iso") or "").strip()
            location = str(call.get("location") or "").strip()
            if not start_iso:
                start_iso = (utc_now() + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0).isoformat() + "Z"
            try:
                cal_res = google_actions_service.create_calendar_event(
                    db,
                    user.id,
                    title=title,
                    start_iso=start_iso,
                    location=location,
                )
                actions_taken.append(
                    {"tool": "schedule_meeting", "summary": f"Scheduled '{title}' on Google Calendar"}
                )
                action_summaries.append(f"Scheduled '{title}' on your Google Calendar ({start_iso}).")
            except Exception as exc:
                action_summaries.append(f"Could not schedule meeting '{title}': {exc}")

        elif t_name == "sync_inbox":
            from app.services.gmail_poller import gmail_polling_service

            try:
                sync_res = gmail_polling_service.poll_user_inbox(db, user.id)
                auto_ran = apply_agent_policies_for_user(db, user.id)
                actions_taken.append(
                    {
                        "tool": "sync_inbox",
                        "summary": f"Synced Gmail: {sync_res.created_tasks} new email(s), {len(auto_ran)} auto-executed",
                    }
                )
                action_summaries.append(
                    f"Synced your Gmail inbox ({sync_res.fetched_messages} checked, {sync_res.created_tasks} new tasks imported, {len(auto_ran)} auto-executed by your rules)."
                )
            except Exception as exc:
                action_summaries.append(f"Inbox sync encountered an error: {exc}")

        elif t_name == "remember_note":
            note = str(call.get("note") or "").strip()
            if note:
                notes = list(policy.memory_notes) if isinstance(policy.memory_notes, list) else []
                if note not in notes:
                    notes.append(note)
                policy.memory_notes = notes
                flag_modified(policy, "memory_notes")
                policy.updated_at = utc_now()
                db.commit()
                actions_taken.append({"tool": "remember_note", "summary": f"Saved to Agent memory: {note}"})
                action_summaries.append(f"I have saved that to my persistent memory: \"{note}\".")

        elif t_name == "clear_memory":
            policy.memory_notes = []
            flag_modified(policy, "memory_notes")
            policy.updated_at = utc_now()
            db.commit()
            actions_taken.append({"tool": "clear_memory", "summary": "Cleared saved memory notes"})
            action_summaries.append("Cleared all custom memory notes.")

    # Compose final agent response text
    ai_reply = str(ai_result.get("reply") or "").strip() if isinstance(ai_result, dict) else ""
    if action_summaries:
        final_reply = "\n\n".join(action_summaries)
        if ai_reply and not any(s[:25].lower() in ai_reply.lower() for s in action_summaries):
            final_reply = f"{final_reply}\n\n{ai_reply}"
    elif ai_reply:
        final_reply = ai_reply
    else:
        direct_query_reply = _answer_workspace_query(cleaned_msg, all_tasks, policy)
        if direct_query_reply:
            final_reply = direct_query_reply
        else:
            # Comprehensive deterministic workspace overview when asked general/help questions
            pending_list = [t for t in all_tasks if t.status == "pending"]
            approved_list = [t for t in all_tasks if t.status == "approved"]
            rejected_list = [t for t in all_tasks if t.status == "rejected"]
            pay_tasks = []
            meet_tasks = []
            for t in pending_list:
                raw = t.raw_data if isinstance(t.raw_data, dict) else {}
                ai = raw.get("ai_analysis") if isinstance(raw.get("ai_analysis"), dict) else {}
                if ai.get("requires_payment"):
                    amt = (ai.get("payment") or {}).get("amount")
                    pay_tasks.append(f"{t.title} (₹{amt})" if amt else t.title)
                elif ai.get("requires_calendar") or t.source == "calendar":
                    meet_tasks.append(t.title)

            rule_desc = (
                f"Auto-Pay enabled for bills <= ₹{policy.auto_pay_max_amount:.2f} {policy.auto_pay_currency}"
                if policy.auto_pay_enabled
                else "Auto-Pay currently off"
            )
            final_reply = (
                f"You currently have {len(pending_list)} pending, {len(approved_list)} approved, and {len(rejected_list)} rejected tasks ({rule_desc}).\n"
                + (f"• Pending Bills ({len(pay_tasks)}): {', '.join(pay_tasks[:5])}\n" if pay_tasks else "")
                + (f"• Pending Meetings ({len(meet_tasks)}): {', '.join(meet_tasks[:5])}\n" if meet_tasks else "")
                + "\nYou can ask me to:\n"
                "• \"Show me the mails I rejected\" (or approved/pending mails, bills, or meetings)\n"
                "• \"Make all payments under 1000 rs automatically without asking\"\n"
                "• \"Automatically archive all informational emails\"\n"
                "• \"Connect Google Drive\" (or Google Sheets, Docs, Contacts, Tasks, Meet)\n"
                "• \"Approve the Water Utility Bill\" or \"Reject the Gym Membership\"\n"
                "• \"Send an email to colleague@example.com with subject ...\""
            )

    stored_actions = list(actions_taken) + [{"_chat_id": effective_chat_id}]
    agent_msg_record = AgentMessage(
        id=str(uuid.uuid4()),
        user_id=user.id,
        role="agent",
        content=final_reply,
        actions_taken=stored_actions,
        created_at=utc_now(),
    )
    db.add(agent_msg_record)
    db.commit()
    db.refresh(agent_msg_record)

    return {
        "user_message": serialize_agent_message(user_msg_record, fallback_chat_id=effective_chat_id),
        "agent_message": serialize_agent_message(agent_msg_record, fallback_chat_id=effective_chat_id),
        "policy": serialize_agent_policy(policy),
        "google_services": list_google_services_for_user(db, user.id),
    }
