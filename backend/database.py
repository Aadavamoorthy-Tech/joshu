"""Database initialization and connection."""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base

# SQLite database URL (local dev)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./chief_of_staff.db")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Create all tables."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """Dependency: get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
