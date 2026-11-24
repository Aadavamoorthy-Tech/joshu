"""SQLAlchemy models for Google-authenticated users, opaque sessions, and OAuth CSRF state."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.database import Base


def utc_now() -> datetime:
    """Return a naive UTC timestamp consistent across SQLite and PostgreSQL."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    """Application user identified by Google OIDC `sub` claim."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(320), unique=True, index=True, nullable=False)
    google_id = Column(String(255), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=False)
    picture_url = Column(String(1024), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    sessions = relationship(
        "Session",
        back_populates="user",
        cascade="all, delete-orphan",
    )


class Session(Base):
    """Opaque UUID bearer session issued by FastAPI (30-day TTL)."""

    __tablename__ = "sessions"

    id = Column(String(64), primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False, index=True)

    user = relationship("User", back_populates="sessions")


class OAuthState(Base):
    """Short-lived single-use CSRF state token stored server-side for OAuth callbacks."""

    __tablename__ = "oauth_states"

    state = Column(String(128), primary_key=True, index=True)
    redirect_uri = Column(String(1024), nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    expires_at = Column(DateTime, nullable=False)
