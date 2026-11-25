"""Joshu — Personal AI Chief of Staff web server (zero third-party dependencies).

Runs identically both in hosted preview and locally from VS Code (`python3 app.py`
on http://localhost:3000) using only the Python 3 standard library plus the Phase 2
`invite_parser` module from `backend/`.

Zero demo data: every inbox item is polled live from the signed-in email account
via either Google Cloud Console OAuth 2.0 (Gmail API) or universal IMAPS (TLS 993).
"""

from __future__ import annotations

import json
import os
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from preview_server.google_oauth_service import (
    GoogleOAuthConfigError,
    GoogleOAuthError,
    GoogleTokenExpiredError,
    get_google_oauth_config,
    load_local_env_files,
)
from preview_server.imap_service import (
    ImapAuthError,
    ImapConnectionError,
    ImapValidationError,
    detect_imap_provider,
)
from preview_server.session_store import MailboxSession, SessionManager
from preview_server.ui_template import APP_HTML, build_oauth_callback_html

load_local_env_files()
SESSION_MANAGER = SessionManager()

_REPO_ROOT = Path(__file__).resolve().parent
_OPEN_DESIGN_AUTH_HTML = (_REPO_ROOT / ".open-design" / "auth.html").resolve()


def _load_ui_html() -> str:
    """Serve the user's .open-design/auth.html UI directly from disk."""
    if _OPEN_DESIGN_AUTH_HTML.is_file():
        return _OPEN_DESIGN_AUTH_HTML.read_text(encoding="utf-8")
    return APP_HTML


SESSION_COOKIE_NAME = "joshu_session"
SESSION_COOKIE_MAX_AGE = 30 * 24 * 60 * 60
_ALLOWED_CSRF_HEADERS = {"fetch", "xmlhttprequest"}


def _session_user_dict(session: MailboxSession) -> Dict[str, Any]:
    return {
        "name": session.display_name,
        "email": session.email,
        "picture_url": session.picture_url,
    }


def _format_session_cookie(value: str, max_age: int, is_https: bool) -> str:
    parts = [
        f"{SESSION_COOKIE_NAME}={value}",
        "Path=/",
        f"Max-Age={max_age}",
        "HttpOnly",
    ]
    if is_https:
        parts.extend(["Secure", "SameSite=None", "Partitioned"])
    else:
        parts.append("SameSite=Lax")
    return "; ".join(parts)


class JoshuHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        return

    def _is_https_request(self) -> bool:
        proto = (self.headers.get("X-Forwarded-Proto") or "http").split(",")[0].strip().lower()
        return proto == "https"

    def _request_origin(self) -> str:
        proto = (self.headers.get("X-Forwarded-Proto") or "http").split(",")[0].strip().lower()
        if proto not in ("http", "https"):
            proto = "http"
        host = (self.headers.get("X-Forwarded-Host") or self.headers.get("Host") or "localhost:3000").split(",")[0].strip()
        return f"{proto}://{host}"

    def _bearer_token(self) -> Optional[str]:
        raw = self.headers.get("Authorization") or ""
        parts = raw.strip().split(" ", 1)
        if len(parts) == 2 and parts[0].lower() == "bearer" and parts[1].strip():
            return parts[1].strip()
        return None

    def _cookie_token(self) -> Optional[str]:
        raw_cookie = self.headers.get("Cookie") or ""
        if not raw_cookie:
            return None
        jar: SimpleCookie = SimpleCookie()
        try:
            jar.load(raw_cookie)
        except Exception:
            return None
        morsel = jar.get(SESSION_COOKIE_NAME)
        if morsel and morsel.value.strip():
            return morsel.value.strip()
        return None

    def _resolve_auth_token(self, require_csrf: bool = False) -> Tuple[Optional[str], bool]:
        """Return (token, csrf_failed) reading Bearer header first, then HttpOnly cookie."""
        bearer = self._bearer_token()
        if bearer:
            return bearer, False

        cookie_token = self._cookie_token()
        if not cookie_token:
            return None, False

        if require_csrf:
            requested_with = (self.headers.get("X-Requested-With") or "").strip().lower()
            if requested_with not in _ALLOWED_CSRF_HEADERS:
                return None, True

        return cookie_token, False

    def _session_cookie_headers(self, session_token: str) -> List[Tuple[str, str]]:
        return [
            (
                "Set-Cookie",
                _format_session_cookie(
                    value=session_token,
                    max_age=SESSION_COOKIE_MAX_AGE,
                    is_https=self._is_https_request(),
                ),
            )
        ]

    def _clear_cookie_headers(self) -> List[Tuple[str, str]]:
        return [
            (
                "Set-Cookie",
                _format_session_cookie(
                    value="",
                    max_age=0,
                    is_https=self._is_https_request(),
                ),
            )
        ]

    def _send_json(
        self,
        status: int,
        payload: Dict[str, Any],
        extra_headers: Optional[List[Tuple[str, str]]] = None,
    ) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        if extra_headers:
            for name, value in extra_headers:
                self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status: int, html_body: str) -> None:
        data = html_body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json_body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(min(length, 65536))
        try:
            parsed = json.loads(raw.decode("utf-8"))
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    def _handle_list_tasks(self, qs: Dict[str, Any]) -> None:
        token, _ = self._resolve_auth_token(require_csrf=False)
        if not token:
            self._send_json(401, {"error": "unauthorized", "message": "Sign in required."})
            return
        status_filter = (qs.get("status", ["all"])[0] or "all").lower()
        source_filter = (qs.get("source", ["all"])[0] or "all").lower()
        result = SESSION_MANAGER.list_tasks(
            token=token,
            status_filter=status_filter,
            source_filter=source_filter,
        )
        if result is None:
            self._send_json(401, {"error": "unauthorized", "message": "Session expired. Please sign in again."})
            return
        self._send_json(200, result)

    def _handle_sync_tasks(self) -> None:
        token, csrf_failed = self._resolve_auth_token(require_csrf=True)
        if csrf_failed:
            self._send_json(
                403,
                {
                    "error": "csrf_header_required",
                    "message": "Missing required X-Requested-With header.",
                },
            )
            return
        if not token:
            self._send_json(401, {"error": "unauthorized", "message": "Sign in required."})
            return
        try:
            session, created = SESSION_MANAGER.sync_now(token)
            if session is None:
                self._send_json(401, {"error": "unauthorized", "message": "Session expired. Please sign in again."})
                return
            self._send_json(
                200,
                {
                    "status": "completed",
                    "created_tasks": created,
                    "session": session.to_public_dict(),
                },
            )
        except (GoogleTokenExpiredError, ImapAuthError) as exc:
            self._send_json(401, {"error": "reauth_required", "message": str(exc)})
        except (ImapValidationError, ImapConnectionError, GoogleOAuthError) as exc:
            self._send_json(502, {"error": "poll_failed", "message": str(exc)})

    def _handle_decide_task(self, task_id: str, action: str) -> None:
        token, csrf_failed = self._resolve_auth_token(require_csrf=True)
        if csrf_failed:
            self._send_json(
                403,
                {
                    "error": "csrf_header_required",
                    "message": "Missing required X-Requested-With header.",
                },
            )
            return
        if not token:
            self._send_json(401, {"error": "unauthorized", "message": "Sign in required."})
            return

        body = self._read_json_body() if action == "reject" else {}
        task, outcome = SESSION_MANAGER.decide_task(
            token=token,
            task_id=task_id,
            action=action,
            reason=body.get("reason") if isinstance(body, dict) else None,
        )
        if outcome == "unauthorized":
            self._send_json(401, {"error": "unauthorized", "message": "Session expired. Please sign in again."})
            return
        if outcome == "not_found" or task is None:
            self._send_json(404, {"error": "task_not_found", "message": "Task not found."})
            return

        self._send_json(
            200,
            {
                "task_id": task["id"],
                "status": task["status"],
                "task": task,
                "message": f"Task {task['status']} successfully.",
            },
        )

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path in ("/", "/auth.html", "/task-dashboard.html"):
            self._send_html(200, _load_ui_html())
            return

        if path == "/health":
            self._send_json(200, {"status": "ok"})
            return

        if path == "/api/config":
            cfg = get_google_oauth_config(self._request_origin())
            self._send_json(
                200,
                {
                    "google_oauth_configured": cfg["configured"],
                    "redirect_uri": cfg["redirect_uri"],
                },
            )
            return

        if path == "/api/providers/detect":
            raw_email = (qs.get("email", [""])[0] or "").strip()
            info = detect_imap_provider(raw_email)
            self._send_json(
                200,
                {
                    "provider": info.provider,
                    "host": info.host,
                    "port": info.port,
                    "detected": info.detected,
                    "hint": info.hint,
                },
            )
            return

        if path == "/auth/callback":
            oauth_err = (qs.get("error", [""])[0] or "").strip()
            if oauth_err:
                self._send_json(
                    400,
                    {
                        "error": "oauth_error",
                        "message": f"Google authorization was declined or failed ({oauth_err}).",
                    },
                )
                return

            code = (qs.get("code", [""])[0] or "").strip()
            state = (qs.get("state", [""])[0] or "").strip()
            if not code or not state:
                self._send_json(
                    400,
                    {
                        "error": "missing_params",
                        "message": "Missing authorization code or state parameter.",
                    },
                )
                return

            try:
                session_token, session, initial_synced = SESSION_MANAGER.complete_google_oauth_direct(
                    code=code,
                    state=state,
                )
                self._send_json(
                    200,
                    {
                        "session_token": session_token,
                        "user": _session_user_dict(session),
                        "session": session.to_public_dict(),
                        "initial_synced": initial_synced,
                    },
                    extra_headers=self._session_cookie_headers(session_token),
                )
            except (ValueError, GoogleOAuthConfigError, GoogleOAuthError) as exc:
                self._send_json(400, {"error": "oauth_callback_failed", "message": str(exc)})
            return

        if path == "/auth/google/callback":
            oauth_err = (qs.get("error", [""])[0] or "").strip()
            if oauth_err:
                self._send_html(
                    400,
                    build_oauth_callback_html(
                        error_message=f"Google authorization was declined or failed ({oauth_err})."
                    ),
                )
                return

            code = (qs.get("code", [""])[0] or "").strip()
            state = (qs.get("state", [""])[0] or "").strip()
            if not code or not state:
                self._send_html(
                    400,
                    build_oauth_callback_html(
                        error_message="Missing authorization code or state parameter from Google."
                    ),
                )
                return

            try:
                exchange_code, origin = SESSION_MANAGER.complete_google_oauth_callback(
                    code=code,
                    state=state,
                )
                self._send_html(
                    200,
                    build_oauth_callback_html(
                        exchange_code=exchange_code,
                        redirect_origin=origin,
                    ),
                )
            except (ValueError, GoogleOAuthConfigError, GoogleOAuthError) as exc:
                self._send_html(
                    400,
                    build_oauth_callback_html(error_message=str(exc)),
                )
            return

        if path in ("/api/auth/me", "/auth/me"):
            token, _ = self._resolve_auth_token(require_csrf=False)
            session = SESSION_MANAGER.get_session(token)
            if session is None:
                self._send_json(401, {"error": "unauthorized", "message": "Sign in required."})
                return
            self._send_json(
                200,
                {
                    "user": _session_user_dict(session),
                    "session": session.to_public_dict(),
                },
            )
            return

        if path in ("/api/tasks", "/tasks"):
            self._handle_list_tasks(qs)
            return

        if path == "/agent/state":
            token, _ = self._resolve_auth_token(require_csrf=False)
            session = SESSION_MANAGER.get_session(token)
            if session is None:
                self._send_json(401, {"error": "unauthorized", "message": "Sign in required."})
                return
            from preview_server.agent_engine import list_google_services, read_runtime_rules_file

            self._send_json(
                200,
                {
                    "policy": dict(session.agent_policy),
                    "google_services": list_google_services(session),
                    "messages": list(session.agent_messages),
                    "runtime_code": read_runtime_rules_file(session.agent_policy),
                },
            )
            return

        self._send_json(404, {"error": "not_found", "message": "Route not found."})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path in ("/api/auth/google/start", "/auth/signin"):
            body = self._read_json_body()
            interval = body.get("poll_interval_minutes", 15)
            requested_redirect = body.get("redirect_uri")
            origin = self._request_origin()
            cfg = get_google_oauth_config(origin)
            try:
                auth_url, redirect_uri = SESSION_MANAGER.start_google_oauth(
                    request_origin=origin,
                    poll_interval_minutes=interval,
                    requested_redirect_uri=str(requested_redirect) if requested_redirect else None,
                )
                self._send_json(
                    200,
                    {
                        "auth_url": auth_url,
                        "redirect_url": auth_url,
                        "redirect_uri": redirect_uri,
                    },
                )
            except GoogleOAuthConfigError as exc:
                self._send_json(
                    400,
                    {
                        "error": "google_oauth_not_configured",
                        "message": str(exc),
                        "redirect_uri": cfg["redirect_uri"],
                    },
                )
            return

        if path == "/api/auth/google/exchange":
            body = self._read_json_body()
            exchange_code = str(body.get("exchange_code") or "").strip()
            redeemed = SESSION_MANAGER.redeem_exchange_code(exchange_code)
            if redeemed is None:
                self._send_json(
                    400,
                    {
                        "error": "invalid_exchange_code",
                        "message": "Sign-in code is invalid or expired. Please sign in again.",
                    },
                )
                return
            session_token, session, initial_synced = redeemed
            self._send_json(
                200,
                {
                    "session_token": session_token,
                    "user": _session_user_dict(session),
                    "session": session.to_public_dict(),
                    "initial_synced": initial_synced,
                },
                extra_headers=self._session_cookie_headers(session_token),
            )
            return

        if path == "/api/auth/imap/signin":
            body = self._read_json_body()
            try:
                token, session, initial_synced = SESSION_MANAGER.sign_in_imap(
                    email_address=str(body.get("email") or ""),
                    password=str(body.get("password") or ""),
                    imap_host=body.get("imap_host"),
                    imap_port=int(body.get("imap_port") or 993),
                    poll_interval_minutes=int(body.get("poll_interval_minutes") or 15),
                )
                self._send_json(
                    200,
                    {
                        "session_token": token,
                        "user": _session_user_dict(session),
                        "session": session.to_public_dict(),
                        "initial_synced": initial_synced,
                    },
                    extra_headers=self._session_cookie_headers(token),
                )
            except ImapValidationError as exc:
                self._send_json(400, {"error": "validation_error", "message": str(exc)})
            except ImapAuthError as exc:
                self._send_json(401, {"error": "imap_auth_failed", "message": str(exc)})
            except ImapConnectionError as exc:
                self._send_json(502, {"error": "imap_connection_failed", "message": str(exc)})
            return

        if path in ("/api/auth/signout", "/auth/logout"):
            token, csrf_failed = self._resolve_auth_token(require_csrf=True)
            if csrf_failed:
                self._send_json(
                    403,
                    {
                        "error": "csrf_header_required",
                        "message": "Missing required X-Requested-With header.",
                    },
                )
                return
            SESSION_MANAGER.sign_out(token)
            self._send_json(
                200,
                {"message": "Signed out successfully."},
                extra_headers=self._clear_cookie_headers(),
            )
            return

        if path == "/agent/chat":
            token, csrf_failed = self._resolve_auth_token(require_csrf=True)
            if csrf_failed:
                self._send_json(
                    403,
                    {
                        "error": "csrf_header_required",
                        "message": "Missing required X-Requested-With header.",
                    },
                )
                return
            session = SESSION_MANAGER.get_session(token)
            if session is None:
                self._send_json(401, {"error": "unauthorized", "message": "Sign in required."})
                return
            body = self._read_json_body()
            message = str(body.get("message") or "").strip()
            if not message:
                self._send_json(400, {"error": "bad_request", "message": "Prompt message cannot be empty."})
                return
            from preview_server.agent_engine import process_preview_agent_chat

            result = process_preview_agent_chat(session, message)
            self._send_json(200, result)
            return

        if path in ("/api/tasks/sync", "/tasks/sync"):
            self._handle_sync_tasks()
            return

        parts = [p for p in path.split("/") if p]
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "tasks" and parts[3] in ("approve", "reject"):
            self._handle_decide_task(parts[2], parts[3])
            return

        if len(parts) == 3 and parts[0] == "tasks" and parts[2] in ("approve", "reject"):
            self._handle_decide_task(parts[1], parts[2])
            return

        self._send_json(404, {"error": "not_found", "message": "Route not found."})

    def do_PATCH(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/polling/config":
            token, csrf_failed = self._resolve_auth_token(require_csrf=True)
            if csrf_failed:
                self._send_json(
                    403,
                    {
                        "error": "csrf_header_required",
                        "message": "Missing required X-Requested-With header.",
                    },
                )
                return
            if not token:
                self._send_json(401, {"error": "unauthorized", "message": "Sign in required."})
                return
            body = self._read_json_body()
            session = SESSION_MANAGER.update_polling_config(
                token=token,
                auto_poll_enabled=body.get("auto_poll_enabled"),
                poll_interval_minutes=body.get("poll_interval_minutes"),
            )
            if session is None:
                self._send_json(401, {"error": "unauthorized", "message": "Session expired. Please sign in again."})
                return
            self._send_json(200, {"session": session.to_public_dict()})
            return

        if parsed.path == "/agent/policy":
            token, csrf_failed = self._resolve_auth_token(require_csrf=True)
            if csrf_failed:
                self._send_json(
                    403,
                    {
                        "error": "csrf_header_required",
                        "message": "Missing required X-Requested-With header.",
                    },
                )
                return
            session = SESSION_MANAGER.get_session(token)
            if session is None:
                self._send_json(401, {"error": "unauthorized", "message": "Sign in required."})
                return
            body = self._read_json_body()
            from preview_server.agent_engine import (
                apply_policy_to_session_tasks,
                sync_runtime_rules_file,
            )

            policy = session.agent_policy
            if "auto_pay_enabled" in body and body["auto_pay_enabled"] is not None:
                policy["auto_pay_enabled"] = bool(body["auto_pay_enabled"])
            if "auto_pay_max_amount" in body and body["auto_pay_max_amount"] is not None:
                policy["auto_pay_max_amount"] = round(float(body["auto_pay_max_amount"]), 2)
            if "auto_pay_currency" in body and body["auto_pay_currency"] is not None:
                policy["auto_pay_currency"] = str(body["auto_pay_currency"] or "INR").strip().upper()[:16]
            if "auto_archive_informational" in body and body["auto_archive_informational"] is not None:
                policy["auto_archive_informational"] = bool(body["auto_archive_informational"])
            if "auto_add_calendar_invites" in body and body["auto_add_calendar_invites"] is not None:
                policy["auto_add_calendar_invites"] = bool(body["auto_add_calendar_invites"])
            if "auto_send_replies" in body and body["auto_send_replies"] is not None:
                policy["auto_send_replies"] = bool(body["auto_send_replies"])
            runtime_code = sync_runtime_rules_file(policy)
            auto_executed = apply_policy_to_session_tasks(session)
            self._send_json(
                200,
                {
                    "policy": dict(policy),
                    "auto_executed": auto_executed,
                    "runtime_code": runtime_code,
                },
            )
            return

        self._send_json(404, {"error": "not_found", "message": "Route not found."})

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/agent/history":
            token, csrf_failed = self._resolve_auth_token(require_csrf=True)
            if csrf_failed:
                self._send_json(
                    403,
                    {
                        "error": "csrf_header_required",
                        "message": "Missing required X-Requested-With header.",
                    },
                )
                return
            session = SESSION_MANAGER.get_session(token)
            if session is None:
                self._send_json(401, {"error": "unauthorized", "message": "Sign in required."})
                return
            session.agent_messages.clear()
            self._send_json(200, {"status": "cleared"})
            return

        self._send_json(404, {"error": "not_found", "message": "Route not found."})


def main() -> None:
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "3000"))
    server = ThreadingHTTPServer((host, port), JoshuHandler)
    print(f"Joshu server listening on http://{host}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
