"""Top-level backend entrypoint preserving `uvicorn main:app` and existing tests."""

from app.main import app

__all__ = ["app"]
