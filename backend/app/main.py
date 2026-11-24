"""FastAPI application entrypoint for Personal AI Chief of Staff (Joshu)."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

load_dotenv()

from app.database import init_db  # noqa: E402
from app.routes.auth import router as auth_router  # noqa: E402


def _load_allowed_origins() -> list[str]:
    default_origins = (
        "http://localhost:3000,"
        "http://localhost:5000,"
        "http://localhost:7777,"
        "http://localhost:8080"
    )
    raw = os.getenv("CORS_ALLOWED_ORIGINS", default_origins)
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Personal AI Chief of Staff API",
    version="0.1.0",
    lifespan=lifespan,
)

# Ensure tables exist even when imported directly without lifespan (e.g. unit tests)
init_db()

app.add_middleware(
    CORSMiddleware,
    allow_origins=_load_allowed_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
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
