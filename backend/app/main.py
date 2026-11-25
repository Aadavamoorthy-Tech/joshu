"""FastAPI application entrypoint for Personal AI Chief of Staff (Joshu)."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

from app.database import init_db  # noqa: E402
from app.routes.auth import router as auth_router  # noqa: E402
from app.routes.tasks import router as tasks_router  # noqa: E402
from app.services.gmail_poller import gmail_polling_scheduler  # noqa: E402


def _load_allowed_origins() -> list[str]:
    """Load allowed CORS origins from environment or use development defaults."""
    # For development: allow any localhost port (Flutter dev server uses random ports)
    # For production: use explicitly configured origins
    env_origins = os.getenv("CORS_ALLOWED_ORIGINS", "").strip()
    
    if env_origins:
        return [origin.strip() for origin in env_origins.split(",") if origin.strip()]
    
    # Development default: allow any localhost/127.0.0.1 port
    # This is safe because localhost is not accessible from the internet
    return [
        "http://localhost:3000",
        "http://localhost:5000",
        "http://localhost:7777",
        "http://localhost:8000",
        "http://localhost:8080",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5000",
        "http://127.0.0.1:8000",
        "http://127.0.0.1:8080",
        "http://localhost",
        "http://127.0.0.1",
    ]


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    gmail_polling_scheduler.start()
    try:
        yield
    finally:
        await gmail_polling_scheduler.stop()


app = FastAPI(
    title="Personal AI Chief of Staff API",
    version="0.2.0",
    lifespan=lifespan,
)

# Ensure tables exist even when imported directly without lifespan (e.g. unit tests)
init_db()

app.add_middleware(
    CORSMiddleware,
    allow_origins=_load_allowed_origins(),
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Requested-With"],
)


@app.exception_handler(HTTPException)
async def structured_http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    """Return consistent structured JSON error payloads across all routes."""
    if isinstance(exc.detail, dict) and {"error", "message", "status"}.issubset(exc.detail.keys()):
        payload = exc.detail
    else:
        payload = {
            "error": "http_error",
            "message": str(exc.detail),
            "status": exc.status_code,
        }
    return JSONResponse(status_code=exc.status_code, content=payload)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check endpoint."""
    return {"status": "ok"}


app.include_router(auth_router)
app.include_router(tasks_router)
