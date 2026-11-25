"""SQLAlchemy models for persistent Joshu Agent autonomous policies, memory, and chat history."""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.database import Base
from app.models.session import utc_now


class AgentPolicy(Base):
    """Per-user autonomous execution rules, auto-payment threshold, extra Google scopes, and agent memory."""

    __tablename__ = "agent_policies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, index=True, nullable=False)
    auto_pay_enabled = Column(Boolean, default=False, nullable=False)
    auto_pay_max_amount = Column(Float, default=0.0, nullable=False)
    auto_pay_currency = Column(String(10), default="INR", nullable=False)
    auto_archive_informational = Column(Boolean, default=False, nullable=False)
    auto_add_calendar_invites = Column(Boolean, default=False, nullable=False)
    auto_send_replies = Column(Boolean, default=False, nullable=False)
    extra_google_scopes = Column(Text, default="", nullable=False)
    memory_notes = Column(JSON, default=list, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    user = relationship("User")


class AgentMessage(Base):
    """Persistent conversation history and tool execution trace for the Joshu Agent."""

    __tablename__ = "agent_messages"

    id = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    actions_taken = Column(JSON, default=list, nullable=False)
    created_at = Column(DateTime, default=utc_now, index=True, nullable=False)

    user = relationship("User")
