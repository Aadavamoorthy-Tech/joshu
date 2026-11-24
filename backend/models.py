"""Database models for Personal AI Chief of Staff."""

from datetime import datetime, timedelta
from sqlalchemy import Column, String, DateTime, Boolean, LargeBinary, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class User(Base):
    """Google OAuth user."""
    __tablename__ = "users"
    
    google_id = Column(String(255), primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True)
    name = Column(String(255))
    picture_url = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    oauth_token = relationship("OAuthToken", back_populates="user", uselist=False, cascade="all, delete-orphan")
    sessions = relationship("Session", back_populates="user", cascade="all, delete-orphan")
    tasks = relationship("Task", back_populates="user", cascade="all, delete-orphan")


class OAuthToken(Base):
    """Encrypted Google OAuth tokens (access + refresh)."""
    __tablename__ = "oauth_tokens"
    
    google_id = Column(String(255), ForeignKey("users.google_id"), primary_key=True)
    access_token_encrypted = Column(LargeBinary, nullable=False)
    refresh_token_encrypted = Column(LargeBinary, nullable=True)
    access_token_expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="oauth_token")


class Session(Base):
    """Flutter app session (returned to client after OAuth)."""
    __tablename__ = "sessions"
    
    session_token = Column(String(255), primary_key=True, index=True)
    google_id = Column(String(255), ForeignKey("users.google_id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, default=lambda: datetime.utcnow() + timedelta(days=30))
    
    # Relationships
    user = relationship("User", back_populates="sessions")


class Task(Base):
    """Approval task (meeting invite, bill, etc.)."""
    __tablename__ = "tasks"
    
    task_id = Column(String(255), primary_key=True, index=True)
    google_id = Column(String(255), ForeignKey("users.google_id"), nullable=False)
    title = Column(String(500), nullable=False)
    description = Column(String(2000), nullable=True)
    task_type = Column(String(50), nullable=False)  # e.g., "meeting_invite", "bill"
    source_data = Column(LargeBinary, nullable=True)  # JSON blob (encrypted)
    status = Column(String(50), default="pending")  # pending, approved, rejected, expired
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    expires_at = Column(DateTime, default=lambda: datetime.utcnow() + timedelta(days=7))
    
    # Relationships
    user = relationship("User", back_populates="tasks")
    audit_logs = relationship("AuditLog", back_populates="task", cascade="all, delete-orphan")


class AuditLog(Base):
    """Action audit trail (approve, reject, error, etc.)."""
    __tablename__ = "audit_logs"
    
    log_id = Column(String(255), primary_key=True, index=True)
    task_id = Column(String(255), ForeignKey("tasks.task_id"), nullable=False)
    action = Column(String(50), nullable=False)  # approve, reject, error, auto_expired
    result = Column(String(2000), nullable=True)  # JSON: success message or error details
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    task = relationship("Task", back_populates="audit_logs")
