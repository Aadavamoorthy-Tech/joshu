"""Universal IMAP-over-TLS inbox polling and RFC 822 / ICS message parsing.

Uses only the Python 3 standard library plus the Phase 2 `invite_parser` module.
Supports any email provider via IMAPS (port 993) with strict SSRF protection,
read-only mailbox selection, and XSS-safe plain-text normalization.
"""

from __future__ import annotations

import base64
import email
import imaplib
import ipaddress
import re
import socket
import ssl
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from email import policy
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# Reuse the real Phase 2 invitation parser from backend/.
_BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.services.invite_parser import (  # noqa: E402
    _strip_html,
    parse_gmail_invite_message,
    sanitize_event_url,
)

EMAIL_REGEX = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}$")
HOSTNAME_REGEX = re.compile(
    r"^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$"
)
_URL_PATTERN = re.compile(r"https://[^\s<>\"')\]}]+", re.IGNORECASE)

ALLOWED_IMAPS_PORTS = (993,)

# Well-known email provider IMAPS settings (port 993 over TLS).
PROVIDER_REGISTRY: Dict[str, Dict[str, Any]] = {
    "gmail.com": {
        "provider": "Gmail",
        "host": "imap.gmail.com",
        "port": 993,
        "hint": "Gmail requires a 16-character Google App Password when 2-Step Verification is enabled.",
    },
    "googlemail.com": {
        "provider": "Gmail",
        "host": "imap.gmail.com",
        "port": 993,
        "hint": "Gmail requires a 16-character Google App Password when 2-Step Verification is enabled.",
    },
    "outlook.com": {
        "provider": "Outlook / Microsoft 365",
        "host": "outlook.office365.com",
        "port": 993,
        "hint": "Ensure IMAP access is enabled in Outlook settings and use an App Password if MFA is active.",
    },
    "hotmail.com": {
        "provider": "Outlook / Hotmail",
        "host": "outlook.office365.com",
        "port": 993,
        "hint": "Ensure IMAP access is enabled in Microsoft account settings.",
    },
    "live.com": {
        "provider": "Outlook / Live",
        "host": "outlook.office365.com",
        "port": 993,
        "hint": "Ensure IMAP access is enabled in Microsoft account settings.",
    },
    "office365.com": {
        "provider": "Microsoft 365",
        "host": "outlook.office365.com",
        "port": 993,
        "hint": "Use your Microsoft 365 credentials or an App Password if MFA is enforced.",
    },
    "yahoo.com": {
        "provider": "Yahoo Mail",
        "host": "imap.mail.yahoo.com",
        "port": 993,
        "hint": "Yahoo Mail requires a generated App Password from Account Security.",
    },
    "ymail.com": {
        "provider": "Yahoo Mail",
        "host": "imap.mail.yahoo.com",
        "port": 993,
        "hint": "Yahoo Mail requires a generated App Password from Account Security.",
    },
    "icloud.com": {
        "provider": "iCloud Mail",
        "host": "imap.mail.me.com",
        "port": 993,
        "hint": "iCloud Mail requires an App-Specific Password from appleid.apple.com.",
    },
    "me.com": {
        "provider": "iCloud Mail",
        "host": "imap.mail.me.com",
        "port": 993,
        "hint": "iCloud Mail requires an App-Specific Password from appleid.apple.com.",
    },
    "mac.com": {
        "provider": "iCloud Mail",
        "host": "imap.mail.me.com",
        "port": 993,
        "hint": "iCloud Mail requires an App-Specific Password from appleid.apple.com.",
    },
    "fastmail.com": {
        "provider": "Fastmail",
        "host": "imap.fastmail.com",
        "port": 993,
        "hint": "Use a Fastmail App Password with IMAP access enabled.",
    },
    "fastmail.fm": {
        "provider": "Fastmail",
        "host": "imap.fastmail.com",
        "port": 993,
        "hint": "Use a Fastmail App Password with IMAP access enabled.",
    },
    "zoho.com": {
        "provider": "Zoho Mail",
        "host": "imap.zoho.com",
        "port": 993,
        "hint": "Enable IMAP in Zoho Mail settings and use an App-Specific Password if 2FA is active.",
    },
    "zohomail.com": {
        "provider": "Zoho Mail",
        "host": "imap.zoho.com",
        "port": 993,
        "hint": "Enable IMAP in Zoho Mail settings and use an App-Specific Password if 2FA is active.",
    },
    "aol.com": {
        "provider": "AOL Mail",
        "host": "imap.aol.com",
        "port": 993,
        "hint": "Generate an App Password in AOL Account Security.",
    },
    "gmx.com": {
        "provider": "GMX Mail",
        "host": "imap.gmx.com",
        "port": 993,
        "hint": "Enable POP3/IMAP access in GMX Mail settings.",
    },
}

_BLOCKED_HOST_SUFFIXES = (
    ".local",
    ".localhost",
    ".internal",
    ".localdomain",
    ".home.arpa",
)


class ImapValidationError(ValueError):
    """Raised when email address or IMAP server settings are invalid or disallowed."""


class ImapAuthError(RuntimeError):
    """Raised when the remote IMAP server rejects credentials."""


class ImapConnectionError(RuntimeError):
    """Raised when the remote IMAP server cannot be reached securely."""


@dataclass(frozen=True)
class ProviderDetection:
    provider: str
    host: str
    port: int
    detected: bool
    hint: str


def normalize_email(raw_email: str) -> str:
    """Validate and normalize an email address."""
    cleaned = (raw_email or "").strip().lower()
    if not cleaned or len(cleaned) > 320 or not EMAIL_REGEX.match(cleaned):
        raise ImapValidationError("Please enter a valid email address.")
    return cleaned


def detect_imap_provider(raw_email: str) -> ProviderDetection:
    """Detect standard IMAPS settings from an email address domain."""
    cleaned = (raw_email or "").strip().lower()
    if "@" not in cleaned:
        return ProviderDetection(
            provider="Custom IMAP",
            host="",
            port=993,
            detected=False,
            hint="Enter your email address to auto-detect IMAP settings.",
        )

    domain = cleaned.rsplit("@", 1)[1].strip()
    if domain in PROVIDER_REGISTRY:
        info = PROVIDER_REGISTRY[domain]
        return ProviderDetection(
            provider=str(info["provider"]),
            host=str(info["host"]),
            port=int(info["port"]),
            detected=True,
            hint=str(info["hint"]),
        )

    # Reasonable default for corporate / custom domains (user can override in Custom IMAP settings).
    suggested_host = f"imap.{domain}" if domain and "." in domain else ""
    return ProviderDetection(
        provider="Custom Domain Mail",
        host=suggested_host,
        port=993,
        detected=False,
        hint="Custom domain detected. Verify or override the IMAP server hostname below if your mail uses Google Workspace (imap.gmail.com) or Microsoft 365 (outlook.office365.com).",
    )


def validate_imap_target(
    raw_host: str,
    raw_port: int = 993,
    resolver: Optional[Callable[[str, int], List[Any]]] = None,
) -> Tuple[str, int]:
    """Validate IMAPS hostname and port, blocking SSRF targets and private/loopback IPs."""
    host = (raw_host or "").strip().lower().rstrip(".")
    if not host or len(host) > 253:
        raise ImapValidationError("IMAP server hostname is required.")

    # Reject raw IP addresses (prevents direct internal IP targeting).
    try:
        ipaddress.ip_address(host)
        raise ImapValidationError("Please enter a valid domain name for the IMAP server, not an IP address.")
    except ValueError:
        pass

    if not HOSTNAME_REGEX.match(host):
        raise ImapValidationError("IMAP server hostname contains invalid characters.")

    if host in ("localhost", "metadata.google.internal") or any(
        host.endswith(suffix) for suffix in _BLOCKED_HOST_SUFFIXES
    ):
        raise ImapValidationError("Private or internal IMAP hostnames are not permitted.")

    try:
        port = int(raw_port)
    except (TypeError, ValueError) as exc:
        raise ImapValidationError("IMAP port must be 993 (IMAPS over TLS).") from exc

    if port not in ALLOWED_IMAPS_PORTS:
        raise ImapValidationError("Only secure IMAPS port 993 (TLS) is supported.")

    # Resolve DNS and verify every resolved IP is strictly public/global.
    lookup = resolver or (lambda h, p: socket.getaddrinfo(h, p, type=socket.SOCK_STREAM))
    try:
        addrinfo = lookup(host, port)
    except socket.gaierror as exc:
        raise ImapConnectionError(
            f"Could not resolve mail server '{host}'. Check the IMAP hostname in Custom IMAP Server settings."
        ) from exc

    if not addrinfo:
        raise ImapConnectionError(f"Mail server '{host}' did not return any reachable addresses.")

    for entry in addrinfo:
        sockaddr = entry[4]
        ip_str = sockaddr[0]
        try:
            ip_obj = ipaddress.ip_address(ip_str)
        except ValueError as exc:
            raise ImapValidationError("Mail server resolved to an invalid network address.") from exc

        if (
            not ip_obj.is_global
            or ip_obj.is_private
            or ip_obj.is_loopback
            or ip_obj.is_link_local
            or ip_obj.is_multicast
            or ip_obj.is_reserved
            or ip_obj.is_unspecified
        ):
            raise ImapValidationError(
                "Connections to private, loopback, or restricted network addresses are blocked."
            )

    return host, port


def _iso_utc(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    else:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _b64url(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8", errors="replace")).decode("ascii").rstrip("=")


def _decode_mime_header(value: Optional[str]) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(str(value)))).strip()
    except Exception:
        return str(value).strip()


def _extract_part_text(part: EmailMessage) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        content = part.get_payload()
        return str(content) if isinstance(content, str) else ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def _rfc822_to_gmail_shape(
    raw_bytes: bytes,
    fallback_id: str,
) -> Tuple[Dict[str, Any], str, Optional[datetime], str, List[str], Optional[str]]:
    """Parse raw RFC 822 bytes into a Gmail-API-compatible payload for `invite_parser` plus email summary metadata."""
    msg = email.message_from_bytes(raw_bytes, policy=policy.default)

    message_id = _decode_mime_header(msg.get("Message-ID")) or fallback_id
    subject = _decode_mime_header(msg.get("Subject")) or "(No Subject)"
    sender = _decode_mime_header(msg.get("From")) or "Unknown Sender"
    to_hdr = _decode_mime_header(msg.get("To"))
    cc_hdr = _decode_mime_header(msg.get("Cc"))
    date_hdr = _decode_mime_header(msg.get("Date"))

    received_dt: Optional[datetime] = None
    if date_hdr:
        try:
            parsed_dt = parsedate_to_datetime(date_hdr)
            if parsed_dt.tzinfo is not None:
                received_dt = parsed_dt.astimezone(timezone.utc).replace(tzinfo=None)
            else:
                received_dt = parsed_dt
        except (TypeError, ValueError):
            received_dt = None

    parts_list: List[Dict[str, Any]] = []
    plain_chunks: List[str] = []
    html_chunks: List[str] = []

    if msg.is_multipart():
        for part in msg.walk():
            if part.is_multipart():
                continue
            ctype = (part.get_content_type() or "").lower()
            filename = (part.get_filename() or "").strip()
            if (
                ctype in ("text/calendar", "application/ics")
                or filename.lower().endswith(".ics")
                or ctype in ("text/plain", "text/html")
            ):
                decoded = _extract_part_text(part)
                if decoded:
                    parts_list.append(
                        {
                            "mimeType": ctype,
                            "filename": filename,
                            "body": {"data": _b64url(decoded)},
                        }
                    )
                    if ctype == "text/plain":
                        plain_chunks.append(decoded)
                    elif ctype == "text/html":
                        html_chunks.append(decoded)
    else:
        ctype = (msg.get_content_type() or "text/plain").lower()
        decoded = _extract_part_text(msg)
        if decoded:
            parts_list.append(
                {
                    "mimeType": ctype,
                    "filename": msg.get_filename() or "",
                    "body": {"data": _b64url(decoded)},
                }
            )
            if ctype == "text/plain":
                plain_chunks.append(decoded)
            elif ctype == "text/html":
                html_chunks.append(decoded)

    plain_text = "\n".join(plain_chunks).strip()
    html_text = "\n".join(_strip_html(h) for h in html_chunks).strip()
    clean_body = plain_text or html_text
    snippet = re.sub(r"\s+", " ", clean_body).strip()[:320]

    # Collect safe external HTTPS URLs from body
    first_safe_url: Optional[str] = None
    for candidate in _URL_PATTERN.findall(plain_text + "\n" + "\n".join(html_chunks)):
        safe = sanitize_event_url(candidate)
        if safe:
            first_safe_url = safe
            break

    # Collect normalized recipient addresses
    recipients: List[str] = []
    for raw_addr in (to_hdr, cc_hdr):
        if not raw_addr:
            continue
        for _, addr in getaddresses([raw_addr]):
            normalized = addr.strip().lower()
            if normalized and "@" in normalized and normalized not in recipients:
                recipients.append(normalized)

    gmail_like_message: Dict[str, Any] = {
        "id": message_id,
        "threadId": _decode_mime_header(msg.get("Thread-Index")) or message_id,
        "snippet": snippet,
        "payload": {
            "headers": [
                {"name": "Subject", "value": subject},
                {"name": "From", "value": sender},
                {"name": "To", "value": to_hdr},
                {"name": "Cc", "value": cc_hdr},
                {"name": "Date", "value": date_hdr},
            ],
            "parts": parts_list,
        },
    }

    return gmail_like_message, clean_body, received_dt, sender, recipients, first_safe_url


def parse_raw_email_bytes(
    raw_bytes: bytes,
    account_email: str,
    fallback_uid: str,
) -> Dict[str, Any]:
    """Convert raw RFC 822 bytes into a normalized Joshu Approval Inbox task dict.

    Calendar/meeting invitations are parsed via `parse_gmail_invite_message`;
    regular inbox emails are normalized safely into `source='email'` items so
    any signed-in mailbox surfaces real inbox data immediately.
    """
    now_iso = _iso_utc(datetime.now(timezone.utc))
    gmail_like, clean_body, received_dt, sender, recipients, first_safe_url = _rfc822_to_gmail_shape(
        raw_bytes, fallback_id=f"imap-{fallback_uid}"
    )

    extracted = parse_gmail_invite_message(gmail_like)
    if extracted is not None:
        return {
            "id": str(uuid.uuid4()),
            "account_email": account_email,
            "external_message_id": extracted.external_message_id,
            "title": extracted.title,
            "description": extracted.description,
            "snippet": re.sub(r"\s+", " ", extracted.description).strip()[:220],
            "scheduled_for": _iso_utc(extracted.scheduled_for or received_dt),
            "source": "calendar" if extracted.source == "calendar" else "email",
            "is_meeting_invite": True,
            "status": "pending",
            "organizer": extracted.organizer or sender,
            "attendees": extracted.attendees or recipients,
            "calendar_event_link": extracted.calendar_event_link,
            "raw_data": extracted.raw_data,
            "created_at": now_iso,
            "updated_at": now_iso,
            "approved_at": None,
            "rejected_at": None,
            "rejection_reason": None,
            "approved_by_user": False,
        }

    # Standard inbox email item (non-calendar invite)
    headers_map = {h["name"].lower(): h["value"] for h in gmail_like["payload"]["headers"]}
    subject = (headers_map.get("subject") or "(No Subject)")[:500]
    summary = clean_body[:1500].strip() if clean_body else "No message body."
    snippet = re.sub(r"\s+", " ", summary).strip()[:220]

    return {
        "id": str(uuid.uuid4()),
        "account_email": account_email,
        "external_message_id": str(gmail_like["id"]),
        "title": subject,
        "description": summary,
        "snippet": snippet,
        "scheduled_for": _iso_utc(received_dt),
        "source": "email",
        "is_meeting_invite": False,
        "status": "pending",
        "organizer": sender,
        "attendees": recipients,
        "calendar_event_link": first_safe_url,
        "raw_data": {
            "message_id": str(gmail_like["id"]),
            "subject": subject,
            "from": sender,
            "date": headers_map.get("date"),
        },
        "created_at": now_iso,
        "updated_at": now_iso,
        "approved_at": None,
        "rejected_at": None,
        "rejection_reason": None,
        "approved_by_user": False,
    }


def fetch_imap_inbox_messages(
    email_address: str,
    password: str,
    imap_host: str,
    imap_port: int = 993,
    max_messages: int = 20,
    timeout_seconds: int = 12,
) -> List[Dict[str, Any]]:
    """Connect over IMAPS (TLS 993), select INBOX read-only, and fetch latest messages."""
    clean_email = normalize_email(email_address)
    if not password or not password.strip():
        raise ImapValidationError("Password or App Password is required.")

    validated_host, validated_port = validate_imap_target(imap_host, imap_port)
    ssl_ctx = ssl.create_default_context()

    conn: Optional[imaplib.IMAP4_SSL] = None
    try:
        conn = imaplib.IMAP4_SSL(
            host=validated_host,
            port=validated_port,
            ssl_context=ssl_ctx,
            timeout=timeout_seconds,
        )
        conn.login(clean_email, password)
    except imaplib.IMAP4.error as exc:
        raw_err = str(exc).lower()
        if any(tok in raw_err for tok in ("auth", "login", "credential", "invalid", "password", "application-specific")):
            raise ImapAuthError(
                "Sign-in was rejected by your mail provider. Double-check your email and use an App Password if 2-Step Verification is enabled."
            ) from exc
        raise ImapConnectionError(
            "The mail server refused the IMAP session. Confirm IMAP access is enabled in your mailbox settings."
        ) from exc
    except (socket.timeout, TimeoutError) as exc:
        raise ImapConnectionError(
            f"Timed out connecting to {validated_host}:{validated_port}. Verify the IMAP hostname and try again."
        ) from exc
    except ssl.SSLError as exc:
        raise ImapConnectionError(
            f"Could not establish a verified TLS connection to {validated_host}."
        ) from exc
    except OSError as exc:
        raise ImapConnectionError(
            f"Could not reach mail server {validated_host}:{validated_port}."
        ) from exc

    tasks: List[Dict[str, Any]] = []
    try:
        status, _ = conn.select("INBOX", readonly=True)
        if status != "OK":
            raise ImapConnectionError("Signed in, but could not open the INBOX folder.")

        status, data = conn.uid("search", None, "ALL")
        if status != "OK" or not data or not data[0]:
            return []

        all_uids = data[0].split()
        recent_uids = list(reversed(all_uids[-max_messages:]))

        for uid_bytes in recent_uids:
            uid_str = uid_bytes.decode("ascii", errors="ignore")
            fetch_status, msg_data = conn.uid("fetch", uid_bytes, "(BODY.PEEK[])")
            if fetch_status != "OK" or not msg_data:
                continue

            raw_bytes: Optional[bytes] = None
            for item in msg_data:
                if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], (bytes, bytearray)):
                    raw_bytes = bytes(item[1])
                    break
            if not raw_bytes:
                continue

            try:
                tasks.append(
                    parse_raw_email_bytes(
                        raw_bytes=raw_bytes,
                        account_email=clean_email,
                        fallback_uid=uid_str,
                    )
                )
            except Exception:
                # Skip malformed individual messages rather than failing the whole poll.
                continue

        return tasks
    finally:
        if conn is not None:
            try:
                conn.logout()
            except Exception:
                pass
