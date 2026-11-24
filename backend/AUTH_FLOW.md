# OAuth 2.0 Sign-In Flow — Joshu Backend & Flutter Architecture

This document describes the end-to-end Google OAuth 2.0 authentication architecture implemented for **Joshu (Personal AI Chief of Staff)**.

## Architecture Overview

FastAPI acts as the **sole OAuth 2.0 broker**. Google OAuth credentials (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`) and authorization code exchanges stay exclusively on the backend. Flutter clients (Web, Android, Windows) only ever receive an opaque UUID v4 `session_token` valid for 30 days.

```
Flutter Client                      FastAPI Backend                       Google OAuth 2.0
--------------                      ---------------                       ----------------
1. Tap "Sign in with Google"
   POST /auth/signin -------------> 2. Generate single-use CSRF `state`,
                                       store in `oauth_states` (10m TTL),
   <-------------------------------    return `{ "redirect_url": "..." }`

3. Open consent screen via
   flutter_web_auth_2 --------------------------------------------------> 4. User signs in
   <---------------------------------------------------------------------    Redirect with ?code=...&state=...
   (Web: /auth.html posts URL back
    to window.opener on same origin)

5. GET /auth/callback?code=&state= -> 6. Verify & consume `state` (single-use)
                                         Exchange `code` with Google --------> 7. Token response + ID token
                                         Cryptographically verify ID token
                                         Upsert `User` by `google_id` (`sub`)
                                         Create 30-day UUID `Session`
   <-----------------------------------  Return `{ session_token, user, expires_at }`

8. Persist `session_token` in platform storage
   Attach `Authorization: Bearer <token>` to protected API calls
```

## Endpoints

### `POST /auth/signin`
Generates a Google OAuth 2.0 authorization URL with `openid email profile` scopes and a cryptographically random single-use `state` token stored server-side.

- **Optional Request Body**:
  ```json
  { "redirect_uri": "http://localhost:3000/auth.html" }
  ```
  If provided, `redirect_uri` must match the server's `ALLOWED_OAUTH_REDIRECT_URIS` allowlist (defaulting to `GOOGLE_REDIRECT_URI`).
- **Response `200 OK`**:
  ```json
  { "redirect_url": "https://accounts.google.com/o/oauth2/v2/auth?..." }
  ```
- **Errors**:
  - `400 invalid_redirect_uri` — Requested redirect URI is not allowlisted.
  - `500 oauth_not_configured` — `GOOGLE_CLIENT_ID` or `GOOGLE_CLIENT_SECRET` missing.

### `GET /auth/callback?code=...&state=...`
Validates and immediately consumes the single-use `state` token, exchanges `code` with Google, cryptographically verifies the OIDC ID token (`google.oauth2.id_token.verify_oauth2_token`), upserts the `User`, and creates a 30-day `Session`.

- **Response `200 OK`**:
  ```json
  {
    "session_token": "550e8400-e29b-41d4-a716-446655440000",
    "user": {
      "email": "user@example.com",
      "name": "User Name",
      "picture_url": "https://lh3.googleusercontent.com/..."
    },
    "expires_at": "2026-12-24T01:55:00Z"
  }
  ```
- **Errors**:
  - `400 oauth_denied` — User declined consent or Google returned an error.
  - `400 missing_code` / `400 missing_state` — Required parameters absent.
  - `400 invalid_state` — Unknown, expired, or already-consumed state token.
  - `400 invalid_code` — Authorization code rejected by Google.
  - `500 id_token_verification_failed` — ID token signature, audience, or issuer check failed.

### `POST /auth/refresh`
Requires `Authorization: Bearer <session_token>`. Issues a new 30-day UUID session token, deactivates the previous session (`is_active = False`), and returns the rotated token plus user profile.

- **Response `200 OK`**:
  ```json
  {
    "session_token": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
    "expires_at": "2026-12-24T01:55:00Z",
    "user": {
      "email": "user@example.com",
      "name": "User Name",
      "picture_url": "https://lh3.googleusercontent.com/..."
    }
  }
  ```
- **Errors**:
  - `401 missing_authorization` / `401 invalid_session` — Missing, expired, or revoked token.

### `POST /auth/logout`
Requires `Authorization: Bearer <session_token>`. Marks the session `is_active = False`.

- **Response `200 OK`**:
  ```json
  { "message": "Logged out successfully" }
  ```
- **Errors**:
  - `401 missing_authorization` / `401 invalid_session` — Missing, expired, or already-revoked token.
  - `404 session_not_found` — Session token does not exist.

### `GET /auth/me`
Requires `Authorization: Bearer <session_token>`. Returns the authenticated user's profile and session expiry without rotating the token.

## Structured Error Format

All auth and HTTP errors return a consistent JSON shape:
```json
{
  "error": "invalid_session",
  "message": "Session token is invalid or expired",
  "status": 401
}
```

## Database Schema (`backend/app/models/session.py`)

- **`users`**: `id`, `google_id` (unique indexed `sub`), `email` (unique indexed), `name`, `picture_url`, `created_at`, `updated_at`
- **`sessions`**: `id` (UUID v4 string PK), `user_id` (FK → `users.id`), `created_at`, `expires_at`, `is_active`
- **`oauth_states`**: `state` (PK, 32-byte URL-safe token), `redirect_uri`, `created_at`, `expires_at` (10-minute TTL)

## Google Cloud Console Configuration

In Google Cloud Console (**APIs & Services → Credentials → OAuth 2.0 Client IDs**, project `joshu-515708`), configure **Authorized redirect URIs**:

- Local backend callback: `http://localhost:8000/auth/callback`
- Local Flutter Web popup relay: `http://localhost:3000/auth.html` (and `http://localhost:8080/auth.html` if running on port 8080)
- Production: `https://<your-domain>/auth/callback` and `https://<your-web-domain>/auth.html`

Configure `backend/.env` from `backend/.env.example` (never commit `.env` or downloaded `client_secret_*.json` files to Git).

## Security Controls

- **Single-use CSRF protection**: Server-generated `state` tokens expire in 10 minutes and are deleted immediately upon callback verification.
- **Strict redirect URI allowlist**: Only server-configured redirect URIs are accepted by `/auth/signin`.
- **Cryptographic ID token verification**: Google OIDC ID tokens are verified against Google's public keys, client ID audience, and issuer.
- **Session rotation & revocation**: `/auth/refresh` rotates session UUIDs and deactivates old tokens; `/auth/logout` immediately revokes tokens.
- **Explicit CORS origins**: Only configured origins are allowed (never wildcard `*` with credentials).
- **Same-origin Web relay**: `app/web/auth.html` posts callback URLs strictly to `window.location.origin`.

## Running Tests Locally

```bash
# Backend unit & integration tests
cd backend
pip install -r requirements.txt pytest httpx
pytest tests/ -v

# Flutter analysis & widget tests
cd ../app
flutter pub get
flutter analyze
flutter test
```
