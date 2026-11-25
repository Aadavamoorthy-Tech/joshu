"""Stdlib-only Joshu Agent engine for preview_server (app.py on port 3000).

Mirrors backend/app/services/agent_service.py so the Agent tab works identically
both in the hosted preview server (app.py) and in the FastAPI backend (port 8000).
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

RUNTIME_RULES_PATH = (
    Path(__file__).resolve().parent.parent
    / "backend"
    / "app"
    / "services"
    / "agent_runtime_rules.py"
)

GOOGLE_SERVICES_CATALOG: List[Dict[str, Any]] = [
    {
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
    {
        "id": "calendar",
        "name": "Google Calendar",
        "scopes": ["https://www.googleapis.com/auth/calendar.events"],
        "description": "Schedule meetings, create Google Calendar events, and RSVP to invites.",
        "keywords": ("calendar", "schedule", "meeting", "events"),
    },
    {
        "id": "drive",
        "name": "Google Drive",
        "scopes": ["https://www.googleapis.com/auth/drive.readonly"],
        "description": "Access and search files, attachments, and shared documents in Google Drive.",
        "keywords": ("drive", "files", "storage", "folder"),
    },
    {
        "id": "docs",
        "name": "Google Docs",
        "scopes": ["https://www.googleapis.com/auth/documents"],
        "description": "Read, draft, and update executive briefings and notes in Google Docs.",
        "keywords": ("docs", "document", "documents"),
    },
    {
        "id": "sheets",
        "name": "Google Sheets",
        "scopes": ["https://www.googleapis.com/auth/spreadsheets"],
        "description": "Log expenses, payment ledgers, and task trackers in Google Sheets.",
        "keywords": ("sheets", "spreadsheet", "spreadsheets", "excel"),
    },
    {
        "id": "contacts",
        "name": "Google Contacts",
        "scopes": ["https://www.googleapis.com/auth/contacts.readonly"],
        "description": "Look up sender profiles, phone numbers, and organization contacts.",
        "keywords": ("contacts", "people", "address book"),
    },
    {
        "id": "tasks",
        "name": "Google Tasks",
        "scopes": ["https://www.googleapis.com/auth/tasks"],
        "description": "Two-way sync action items with Google Tasks lists.",
        "keywords": ("google tasks", "to-do", "todo"),
    },
    {
        "id": "meet",
        "name": "Google Meet",
        "scopes": ["https://www.googleapis.com/auth/calendar.events"],
        "description": "Generate Google Meet video conference links for scheduled meetings.",
        "keywords": ("meet", "video call", "conference"),
    },
]


def default_agent_policy() -> Dict[str, Any]:
    return {
        "auto_pay_enabled": False,
        "auto_pay_max_amount": 0.0,
        "auto_pay_currency": "INR",
        "auto_archive_informational": False,
        "auto_add_calendar_invites": False,
        "auto_send_replies": False,
        "custom_instructions": [],
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def sync_runtime_rules_file(policy: Dict[str, Any]) -> str:
    """Write live Python runtime rules module to backend/app/services/agent_runtime_rules.py."""
    enabled = bool(policy.get("auto_pay_enabled"))
    max_amount = round(float(policy.get("auto_pay_max_amount") or 0.0), 2)
    raw_cur = str(policy.get("auto_pay_currency") or "INR").strip().upper()
    currency = raw_cur if re.match(r"^[A-Z]{3}$", raw_cur) else "INR"
    auto_archive = bool(policy.get("auto_archive_informational"))
    auto_calendar = bool(policy.get("auto_add_calendar_invites"))
    auto_replies = bool(policy.get("auto_send_replies"))

    code = f'''"""Auto-generated runtime execution rules managed by Joshu Agent.

This module is automatically updated whenever the user instructs the Joshu Agent
to modify autonomous behavior (such as auto-paying bills under a threshold,
auto-archiving informational emails, or auto-scheduling calendar invites).
"""

from __future__ import annotations

AUTO_PAY_ENABLED: bool = {enabled}
AUTO_PAY_MAX_AMOUNT: float = {max_amount}
AUTO_PAY_CURRENCY: str = "{currency}"
AUTO_ARCHIVE_INFORMATIONAL: bool = {auto_archive}
AUTO_ADD_CALENDAR_INVITES: bool = {auto_calendar}
AUTO_SEND_REPLIES: bool = {auto_replies}


def should_auto_execute_payment(amount: float | int | None, currency: str = "INR") -> bool:
    """Return True if a payment of `amount` should be executed automatically without asking the user."""
    if not AUTO_PAY_ENABLED or amount is None:
        return False
    try:
        numeric_amount = float(amount)
    except (TypeError, ValueError):
        return False
    return 0.0 < numeric_amount <= AUTO_PAY_MAX_AMOUNT
'''
    try:
        RUNTIME_RULES_PATH.parent.mkdir(parents=True, exist_ok=True)
        RUNTIME_RULES_PATH.write_text(code, encoding="utf-8")
    except Exception:
        pass
    return code


def read_runtime_rules_file(policy: Dict[str, Any]) -> str:
    try:
        if RUNTIME_RULES_PATH.is_file():
            return RUNTIME_RULES_PATH.read_text(encoding="utf-8")
    except Exception:
        pass
    return sync_runtime_rules_file(policy)


def list_google_services(session: Any) -> List[Dict[str, Any]]:
    connected = set(getattr(session, "agent_connected_services", ["gmail", "calendar"]))
    items: List[Dict[str, Any]] = []
    for svc in GOOGLE_SERVICES_CATALOG:
        items.append(
            {
                "id": svc["id"],
                "name": svc["name"],
                "description": svc["description"],
                "scopes": list(svc["scopes"]),
                "connected": svc["id"] in connected,
            }
        )
    return items


def apply_policy_to_session_tasks(session: Any) -> List[Dict[str, Any]]:
    """Auto-approve matching pending tasks in the session based on active agent policy."""
    policy = session.agent_policy
    auto_executed: List[Dict[str, Any]] = []
    now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    for task in session.tasks:
        if task.get("status") != "pending":
            continue
        title_lower = str(task.get("title") or "").lower()
        desc_lower = str(task.get("description") or "").lower()
        combined = f"{title_lower} {desc_lower}"

        should_approve = False
        reason = ""

        if policy.get("auto_pay_enabled") and float(policy.get("auto_pay_max_amount") or 0) > 0:
            amt_match = re.search(
                r"(?:rs\.?|inr|₹|\$)\s*(\d+(?:,\d{3})*(?:\.\d{1,2})?)|(\d+(?:,\d{3})*(?:\.\d{1,2})?)\s*(?:rs\.?|inr|rupees|₹)",
                combined,
                re.I,
            )
            if amt_match:
                raw_num = (amt_match.group(1) or amt_match.group(2) or "0").replace(",", "")
                try:
                    val = float(raw_num)
                    if 0 < val <= float(policy["auto_pay_max_amount"]):
                        should_approve = True
                        reason = f"Auto-paid ₹{val:g} (<= ₹{policy['auto_pay_max_amount']:g} threshold)"
                except ValueError:
                    pass

        if not should_approve and policy.get("auto_add_calendar_invites"):
            if task.get("source") == "calendar" or task.get("is_meeting_invite"):
                should_approve = True
                reason = "Auto-scheduled meeting invitation"

        if not should_approve and policy.get("auto_archive_informational"):
            if task.get("source") == "email" and not task.get("is_meeting_invite"):
                should_approve = True
                reason = "Auto-archived informational email"

        if should_approve:
            task["status"] = "approved"
            task["approved_by_user"] = True
            task["approved_at"] = now_iso
            task["updated_at"] = now_iso
            auto_executed.append({"task_id": task.get("id"), "title": task.get("title"), "summary": reason})

    return auto_executed


def process_preview_agent_chat(
    session: Any,
    user_prompt: str,
    chat_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Process a user prompt in the preview server Agent tab."""
    policy = session.agent_policy
    lower = user_prompt.lower().strip()
    actions_taken: List[Dict[str, Any]] = []
    reply_parts: List[str] = []

    # 1. Detect automatic payment threshold rule
    pay_rule_match = re.search(
        r"(?:pay|payment|payments|bill|bills).*?(?:under|below|less than|up to|<=|max|maximum)\s*(?:rs\.?|inr|₹)?\s*(\d+(?:,\d{3})*(?:\.\d{1,2})?)\s*(?:rs\.?|inr|rupees|₹)?",
        lower,
        re.I,
    )
    if not pay_rule_match:
        pay_rule_match = re.search(
            r"(?:under|below|less than|up to|<=)\s*(?:rs\.?|inr|₹)?\s*(\d+(?:,\d{3})*(?:\.\d{1,2})?)\s*(?:rs\.?|inr|rupees|₹)?.*?(?:pay|payment|payments|bill|bills|automatically)",
            lower,
            re.I,
        )

    if pay_rule_match:
        amount = float(pay_rule_match.group(1).replace(",", ""))
        policy["auto_pay_enabled"] = amount > 0
        policy["auto_pay_max_amount"] = round(amount, 2)
        policy["auto_pay_currency"] = "INR"
        policy["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        custom = list(policy.get("custom_instructions") or [])
        custom.append(user_prompt)
        policy["custom_instructions"] = custom[-20:]
        sync_runtime_rules_file(policy)
        auto_exec = apply_policy_to_session_tasks(session)
        summary = (
            f"Enabled automatic payments for all bills <= ₹{amount:g} INR and updated backend/app/services/agent_runtime_rules.py."
        )
        actions_taken.append(
            {
                "tool": "set_auto_payment_rule",
                "summary": summary,
                "auto_executed": auto_exec,
                "show_rules": True,
            }
        )
        reply_parts.append(
            f"Done — I have saved your rule and updated the live runtime policy code (`agent_runtime_rules.py`) so all payments and bills up to ₹{amount:g} INR are executed automatically without asking for confirmation."
            + (f" I also automatically processed {len(auto_exec)} matching pending task(s)." if auto_exec else "")
        )

    # 2. Detect Google service connection request
    for svc in GOOGLE_SERVICES_CATALOG:
        if any(kw in lower for kw in svc["keywords"]) and any(
            verb in lower for verb in ("connect", "link", "integrate", "add", "enable", "authorize", "setup", "set up")
        ):
            actions_taken.append(
                {
                    "tool": "connect_google_service",
                    "summary": f"Prepared Google OAuth connection for {svc['name']}",
                    "connect_service": svc["id"],
                    "service_name": svc["name"],
                    "scopes": list(svc["scopes"]),
                    "show_services": True,
                }
            )
            reply_parts.append(
                f"I've prepared the Google OAuth connection for **{svc['name']}** ({svc['description']}). Click the authorization button below to grant Joshu access."
            )
            break

    # 3. Detect inquiry about active rules or connected Google services
    if not actions_taken and any(
        k in lower for k in ("rule", "rules", "policy", "policies", "automate", "automatic", "auto-pay")
    ):
        actions_taken.append(
            {
                "tool": "show_autonomous_rules",
                "summary": "Displayed active autonomous rules.",
                "show_rules": True,
            }
        )
        pay_status = (
            f"Enabled (<= ₹{policy['auto_pay_max_amount']:g} {policy['auto_pay_currency']})"
            if policy.get("auto_pay_enabled")
            else "Off"
        )
        reply_parts.append(
            f"Here are your active autonomous rules (Auto-Pay Bills: {pay_status}). You can toggle any rule below or tell me a new threshold."
        )

    if not actions_taken and any(
        k in lower for k in ("google service", "google services", "connected service", "connect google", "which services", "integrations")
    ):
        actions_taken.append(
            {
                "tool": "list_connectable_google_services",
                "summary": "Listed Google Workspace services available for Joshu.",
                "show_services": True,
            }
        )
        reply_parts.append(
            "Here are the Google Workspace services you can connect to Joshu. Click any service chip below to authorize it."
        )

    # 4. General response (Gemini API via stdlib urllib if configured, else intelligent summary)
    if not reply_parts:
        gemini_reply = _call_gemini_stdlib(session, user_prompt)
        if gemini_reply:
            reply_parts.append(gemini_reply)
        else:
            pending_count = sum(1 for t in session.tasks if t.get("status") == "pending")
            approved_count = sum(1 for t in session.tasks if t.get("status") == "approved")
            reply_parts.append(
                f"I am your Joshu Agent with full control over this application. Right now you have {pending_count} pending task(s) and {approved_count} approved task(s). "
                "You can tell me to automate payments under a specific amount (e.g., 'Make all payments under 1000 Rs automatically without asking'), connect additional Google services (Drive, Sheets, Docs, Contacts, Tasks, Meet), or manage your inbox tasks."
            )

    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    next_id = len(session.agent_messages) + 1
    effective_chat_id = (str(chat_id or "").strip() or f"chat-{next_id}")[:120]
    user_msg = {
        "id": next_id,
        "chat_id": effective_chat_id,
        "role": "user",
        "content": user_prompt,
        "actions_taken": [],
        "created_at": now_iso,
    }
    agent_msg = {
        "id": next_id + 1,
        "chat_id": effective_chat_id,
        "role": "assistant",
        "content": "\n\n".join(reply_parts),
        "actions_taken": actions_taken,
        "created_at": now_iso,
    }
    session.agent_messages.append(user_msg)
    session.agent_messages.append(agent_msg)

    return {
        "user_message": user_msg,
        "agent_message": agent_msg,
        "policy": dict(policy),
        "google_services": list_google_services(session),
        "runtime_code": read_runtime_rules_file(policy),
    }


def _call_gemini_stdlib(session: Any, user_prompt: str) -> Optional[str]:
    api_key = (os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key or api_key.upper().startswith(("YOUR_", "REPLACE_", "<")):
        return None

    pending = [t.get("title") for t in session.tasks if t.get("status") == "pending"][:10]
    system_text = (
        "You are Joshu Agent, an autonomous AI Chief of Staff inside the Joshu application with full control over tasks, "
        "autonomous payment/inbox policies, and Google Workspace integrations. "
        f"Signed-in user: {session.email}. Pending tasks ({len(pending)}): {', '.join(str(x) for x in pending if x) or 'None'}. "
        "Respond concisely and helpfully."
    )
    payload = {
        "system_instruction": {"parts": [{"text": system_text}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
    }
    body = json.dumps(payload).encode("utf-8")
    for model in ("gemini-2.5-flash", "gemini-2.0-flash"):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": api_key,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                candidates = data.get("candidates") or []
                if candidates:
                    parts = ((candidates[0].get("content") or {}).get("parts")) or []
                    text = "".join(str(p.get("text") or "") for p in parts).strip()
                    if text:
                        return text
        except Exception:
            continue
    return None
