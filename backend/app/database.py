"""SQLAlchemy database engine, session factory, Base declaration, and idempotent schema upgrades."""

from __future__ import annotations

import os
from typing import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./chief_of_staff.db")

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Static, allowlisted DDL upgrades for pre-existing Phase 2 SQLite/PostgreSQL tables.
_TASK_APPROVAL_COLUMN_MIGRATIONS: tuple[tuple[str, str], ...] = (
    ("approved_at", "ALTER TABLE tasks ADD COLUMN approved_at DATETIME"),
    ("rejected_at", "ALTER TABLE tasks ADD COLUMN rejected_at DATETIME"),
    ("rejection_reason", "ALTER TABLE tasks ADD COLUMN rejection_reason VARCHAR(500)"),
    ("approved_by_user", "ALTER TABLE tasks ADD COLUMN approved_by_user BOOLEAN NOT NULL DEFAULT 0"),
)


def ensure_task_approval_columns(target_engine: Engine) -> None:
    """Idempotently add Phase 3 approval columns if an existing `tasks` table predates them."""
    inspector = inspect(target_engine)
    if "tasks" not in inspector.get_table_names():
        return

    existing_columns = {col["name"] for col in inspector.get_columns("tasks")}
    missing = [
        ddl for col_name, ddl in _TASK_APPROVAL_COLUMN_MIGRATIONS if col_name not in existing_columns
    ]
    if not missing:
        return

    is_postgres = target_engine.dialect.name.startswith("postgres")
    with target_engine.begin() as conn:
        for ddl in missing:
            statement = ddl
            if is_postgres:
                statement = (
                    statement.replace("DATETIME", "TIMESTAMP")
                    .replace("DEFAULT 0", "DEFAULT FALSE")
                )
            conn.execute(text(statement))


def init_db() -> None:
    """Ensure all SQLAlchemy models are imported, tables exist, and incremental columns are applied."""
    from app.models import session as _session_models  # noqa: F401
    from app.models import task as _task_models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    ensure_task_approval_columns(engine)


def get_db() -> Generator[DBSession, None, None]:
    """FastAPI dependency yielding a scoped database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
