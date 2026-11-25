"""REST endpoints for Joshu Agent chatbot, autonomous rules, and Google service connections."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from app.database import get_db
from app.middleware.auth import get_current_session
from app.models.agent import AgentMessage
from app.models.session import Session as UserSession
from app.services.agent_service import (
    RUNTIME_RULES_PATH,
    apply_agent_policies_for_user,
    get_or_create_agent_policy,
    list_google_services_for_user,
    process_agent_chat,
    serialize_agent_message_list,
    serialize_agent_policy,
    sync_runtime_rules_code,
)

router = APIRouter(prefix="/agent", tags=["agent"])


class AgentChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    chat_id: Optional[str] = Field(default=None, max_length=120)


class AgentPolicyUpdateRequest(BaseModel):
    auto_pay_enabled: Optional[bool] = None
    auto_pay_max_amount: Optional[float] = Field(default=None, ge=0.0, le=10000000.0)
    auto_pay_currency: Optional[str] = Field(default=None, max_length=16)
    auto_archive_informational: Optional[bool] = None
    auto_add_calendar_invites: Optional[bool] = None
    auto_send_replies: Optional[bool] = None


def _read_runtime_code() -> str:
    try:
        return RUNTIME_RULES_PATH.read_text(encoding="utf-8")
    except Exception:
        return ""


@router.get("/state")
def get_agent_state(
    current_session: UserSession = Depends(get_current_session),
    db: DBSession = Depends(get_db),
):
    """Return active agent policies, connected Google services, chat history, and live runtime code."""
    policy = get_or_create_agent_policy(db, current_session.user_id)
    messages = (
        db.query(AgentMessage)
        .filter(AgentMessage.user_id == current_session.user_id)
        .order_by(AgentMessage.created_at.asc(), AgentMessage.id.asc())
        .limit(200)
        .all()
    )
    return {
        "policy": serialize_agent_policy(policy),
        "google_services": list_google_services_for_user(db, current_session.user_id),
        "messages": serialize_agent_message_list(messages),
        "runtime_code": _read_runtime_code(),
    }


@router.post("/chat")
def chat_with_agent(
    payload: AgentChatRequest,
    current_session: UserSession = Depends(get_current_session),
    db: DBSession = Depends(get_db),
):
    """Send a prompt to the Joshu Agent with full application control."""
    cleaned = (payload.message or "").strip()
    if not cleaned:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Prompt message cannot be empty.",
        )
    result = process_agent_chat(
        db,
        current_session.user,
        cleaned,
        chat_id=payload.chat_id,
    )
    result["runtime_code"] = _read_runtime_code()
    return result


@router.patch("/policy")
def update_agent_policy(
    payload: AgentPolicyUpdateRequest,
    current_session: UserSession = Depends(get_current_session),
    db: DBSession = Depends(get_db),
):
    """Directly toggle or update autonomous agent policies and rewrite live runtime rules."""
    policy = get_or_create_agent_policy(db, current_session.user_id)
    if payload.auto_pay_enabled is not None:
        policy.auto_pay_enabled = bool(payload.auto_pay_enabled)
    if payload.auto_pay_max_amount is not None:
        policy.auto_pay_max_amount = round(float(payload.auto_pay_max_amount), 2)
    if payload.auto_pay_currency is not None:
        policy.auto_pay_currency = (payload.auto_pay_currency or "INR").strip().upper()[:16]
    if payload.auto_archive_informational is not None:
        policy.auto_archive_informational = bool(payload.auto_archive_informational)
    if payload.auto_add_calendar_invites is not None:
        policy.auto_add_calendar_invites = bool(payload.auto_add_calendar_invites)
    if payload.auto_send_replies is not None:
        policy.auto_send_replies = bool(payload.auto_send_replies)

    db.commit()
    db.refresh(policy)
    runtime_code = sync_runtime_rules_code(policy)
    auto_executed = apply_agent_policies_for_user(db, current_session.user_id)

    return {
        "policy": serialize_agent_policy(policy),
        "auto_executed": auto_executed,
        "runtime_code": runtime_code,
    }


@router.delete("/history")
def clear_agent_history(
    chat_id: Optional[str] = Query(default=None),
    message_id: Optional[str] = Query(default=None),
    current_session: UserSession = Depends(get_current_session),
    db: DBSession = Depends(get_db),
):
    """Delete a specific chat session from history (or all if neither chat_id nor message_id is specified)."""
    target_chat_id = (chat_id or "").strip()
    target_msg_id = (message_id or "").strip()

    if target_chat_id or target_msg_id:
        all_msgs = (
            db.query(AgentMessage)
            .filter(AgentMessage.user_id == current_session.user_id)
            .order_by(AgentMessage.created_at.asc(), AgentMessage.id.asc())
            .all()
        )
        serialized = serialize_agent_message_list(all_msgs)
        ids_to_delete = set()
        for raw_msg, ser_msg in zip(all_msgs, serialized):
            if (target_chat_id and ser_msg.get("chat_id") == target_chat_id) or (
                target_msg_id and str(raw_msg.id) == target_msg_id
            ):
                ids_to_delete.add(raw_msg.id)
        if ids_to_delete:
            db.query(AgentMessage).filter(
                AgentMessage.user_id == current_session.user_id,
                AgentMessage.id.in_(list(ids_to_delete)),
            ).delete(synchronize_session=False)
            db.commit()
        return {"status": "deleted", "deleted_count": len(ids_to_delete)}

    db.query(AgentMessage).filter(AgentMessage.user_id == current_session.user_id).delete(
        synchronize_session=False
    )
    db.commit()
    return {"status": "cleared"}
