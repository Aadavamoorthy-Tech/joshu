# Phase 2: Gmail Polling Worker & Tasks API — Joshu Backend

This document describes the background Gmail polling worker, iCalendar/email invitation extractor, database schema, and authenticated `/tasks` endpoints implemented in Phase 2.

## Architecture Overview

1. **OAuth Scope & Encrypted Credential Custody**:
   - `POST /auth/signin` requests `openid`, `email`, `profile`, and `https://www.googleapis.com/auth/gmail.readonly` with `access_type="offline"`.
   - On `GET /auth/callback`, Google `access_token` and `refresh_token` are encrypted with Fernet symmetric encryption (`ENCRYPTION_KEY`) and saved in `google_oauth_tokens`. Google tokens are never returned to clients.
   - `GET /auth/me` exposes `granted_scopes` and `google_reconnect_required` alongside user profile and session expiry.

2. **Scheduled Background Worker (`backend/app/services/gmail_poller.py`)**:
   - `GmailPollingScheduler` starts inside FastAPI's `lifespan` context manager and runs every `GMAIL_POLL_INTERVAL_MINUTES` (default `15`).
   - Each cycle queries active sessions whose users have valid, non-expired Google OAuth credentials (`needs_reconnect = False`), silently refreshes expired Google access tokens, fetches recent calendar invitations via `google-api-python-client` (`gmail` v1), extracts meeting details via `invite_parser.py`, and inserts deduplicated `Task` records.
   - Isolated per-user error handling ensures an expired token or network hiccup for one user never blocks polling for other users.

3. **Deterministic Invitation Parser (`backend/app/services/invite_parser.py`)**:
   - Parses RFC 5545 `.ics` / `text/calendar` MIME parts (including folded lines, escaped commas/semicolons, UTC & TZID timestamps, attendees, organizer, and conference links) as well as fallback plain-text/HTML email invitations.
   - Extracts:
     - **Meeting title** (`title`)
     - **Date/time** (`scheduled_for` UTC)
     - **Attendees & organizer** (`raw_data.attendees`, `raw_data.organizer`, plus summary in `description`)
     - **Calendar / conferencing event link** (`raw_data.calendar_event_link`, strictly validated as external `https://` URLs)

## Database Schema (`backend/app/models/task.py`)

### `tasks`
| Column | Type | Notes |
|--------|------|-------|
| `id` | `String(64)` (PK) | UUID v4 |
| `user_id` | `Integer` (FK → `users.id`) | Indexed, strict tenant ownership |
| `title` | `String(500)` | Extracted meeting title |
| `description` | `Text` | Formatted organizer, attendees, link, and invite notes |
| `scheduled_for` | `DateTime` | Extracted UTC meeting start time |
| `source` | `String(32)` | `"calendar"` (ICS) or `"email"` (email body fallback) |
| `status` | `String(32)` | `"pending"` (default), `"approved"`, `"rejected"` |
| `external_message_id` | `String(255)` | Unique per `(user_id, external_message_id)` for idempotent polling |
| `raw_data` | `JSON` | Full extracted metadata (`attendees`, `organizer`, `calendar_event_link`, `location`, `ics_uid`, `start_time`, `end_time`, `timezone`) |
| `created_at` / `updated_at` | `DateTime` | UTC timestamps |

### `google_oauth_tokens`
| Column | Type | Notes |
|--------|------|-------|
| `id` | `Integer` (PK) | Auto-increment |
| `user_id` | `Integer` (FK → `users.id`, unique) | One credential record per user |
| `encrypted_access_token` | `Text` | Fernet-encrypted Google access token |
| `encrypted_refresh_token` | `Text` | Fernet-encrypted Google refresh token |
| `token_expiry` | `DateTime` | Access token expiration UTC |
| `scopes` | `Text` | Space-delimited granted OAuth scopes |
| `needs_reconnect` | `Boolean` | Set `True` on `RefreshError` / `invalid_grant` (7-day Testing cap) |
| `last_synced_at` | `DateTime` | Timestamp of last successful Gmail sync |
| `last_error` | `String(255)` | Safe diagnostic status (never contains tokens or emails) |

## Endpoints (All Require `Authorization: Bearer <session_token>`)

- **`GET /tasks`**
  - Query params: `status` (`pending|approved|rejected`), `source` (`email|calendar`), `limit` (`1..200`, default `50`), `offset` (`>=0`).
  - Returns `{ "tasks": [...], "total": N, "limit": 50, "offset": 0 }` filtered strictly to the authenticated user.
- **`GET /tasks/{task_id}`**
  - Returns `{ "task": {...} }` if owned by the authenticated user, otherwise `404 task_not_found`.
- **`POST /tasks/sync`**
  - Optional query param: `?background=true` to enqueue via FastAPI `BackgroundTasks`.
  - Runs Gmail polling immediately and returns `{ "status": "completed", "fetched_messages": N, "created_tasks": M, "skipped_duplicates": K, "ignored_non_invites": J, "synced_at": "..." }`.
  - Error responses:
    - `403 google_token_expired` — Google refresh token expired/revoked (user should reconnect).
    - `403 scope_upgrade_required` — `gmail.readonly` scope not yet granted.
    - `502 gmail_api_error` — Temporary network or Gmail API outage.
- **`GET /tasks/sync/status`**
  - Returns `gmail_connected`, `google_reconnect_required`, `last_synced_at`, `last_error`, `poll_interval_minutes`, and `scheduler_running`.

## Configuration (`backend/.env`)

```env
ENCRYPTION_KEY=<fernet-key>
GMAIL_POLLING_ENABLED=true
GMAIL_POLL_INTERVAL_MINUTES=15
GMAIL_MAX_MESSAGES_PER_POLL=25
```

## Running Tests Locally

```bash
cd backend
pip install -r requirements.txt pytest httpx

# Pure invite parser unit tests (stdlib)
python3 -m unittest tests/test_invite_parser.py -v

# Full backend integration test suite
pytest tests/ -v
```
