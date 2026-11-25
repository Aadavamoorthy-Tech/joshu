"""SQLAlchemy models for encrypted Google OAuth credentials and extracted meeting tasks."""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.database import Base
from app.models.session import utc_now


class GoogleOAuthToken(Base):
    """Encrypted server-side Google OAuth access/refresh credentials for background polling."""

    __tablename__ = "google_oauth_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, index=True, nullable=False)
    encrypted_access_token = Column(Text, nullable=False)
    encrypted_refresh_token = Column(Text, nullable=True)
    token_expiry = Column(DateTime, nullable=True)
    scopes = Column(Text, nullable=False, default="openid email profile")
    needs_reconnect = Column(Boolean, default=False, nullable=False, index=True)
    last_synced_at = Column(DateTime, nullable=True)
    last_error = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    user = relationship("User", back_populates="google_token")

    def scope_list(self) -> list[str]:
        return [s for s in (self.scopes or "").split() if s]

    def has_gmail_readonly(self) -> bool:
        scopes = set(self.scope_list())
        return bool(
            scopes.intersection(
                {
                    "https://www.googleapis.com/auth/gmail.readonly",
                    "https://www.googleapis.com/auth/gmail.modify",
                    "https://mail.google.com/",
                    "gmail.readonly",
                    "gmail.modify",
                }
            )
        )

    def has_gmail_modify(self) -> bool:
        scopes = set(self.scope_list())
        return bool(
            scopes.intersection(
                {
                    "https://www.googleapis.com/auth/gmail.modify",
                    "https://mail.google.com/",
                    "gmail.modify",
                }
            )
        )

    def has_gmail_send(self) -> bool:
        scopes = set(self.scope_list())
        return bool(
            scopes.intersection(
                {
                    "https://www.googleapis.com/auth/gmail.send",
                    "https://mail.google.com/",
                    "gmail.send",
                }
            )
        )

    def has_calendar_events(self) -> bool:
        scopes = set(self.scope_list())
        return bool(
            scopes.intersection(
                {
                    "https://www.googleapis.com/auth/calendar.events",
                    "https://www.googleapis.com/auth/calendar",
                    "calendar.events",
                }
            )
        )


class Task(Base):
    """Extracted meeting invite or administrative task awaiting user approval."""

    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("user_id", "external_message_id", name="uq_tasks_user_external_msg"),
    )

    id = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    scheduled_for = Column(DateTime, nullable=True, index=True)
    source = Column(String(32), nullable=False, default="email", index=True)
    status = Column(String(32), nullable=False, default="pending", index=True)
    approved_at = Column(DateTime, nullable=True)
    rejected_at = Column(DateTime, nullable=True)
    rejection_reason = Column(String(500), nullable=True)
    approved_by_user = Column(Boolean, default=False, nullable=False)
    external_message_id = Column(String(255), nullable=True, index=True)
    raw_data = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    user = relationship("User", back_populates="tasks")
