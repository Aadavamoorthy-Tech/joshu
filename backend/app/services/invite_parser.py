"""Pure, deterministic parser for extracting meeting invitations from Gmail messages & ICS attachments.

Uses only the Python standard library so parsing logic is fast, dependency-free, and unit-testable.
"""

from __future__ import annotations

import base64
import html
import ipaddress
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import getaddresses, parsedate_to_datetime
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse

_CALENDAR_LINK_HOSTS = (
    "calendar.google.com",
    "meet.google.com",
    "zoom.us",
    "teams.microsoft.com",
    "outlook.office365.com",
    "outlook.live.com",
    "webex.com",
    "cal.com",
    "calendly.com",
)

_INVITE_SUBJECT_PREFIXES = (
    "invitation:",
    "updated invitation:",
    "canceled event:",
    "cancelled event:",
    "meeting invitation:",
    "calendar invite:",
)

_URL_PATTERN = re.compile(r"https://[^\s<>\"')\]}]+", re.IGNORECASE)
_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
_INVITE_BODY_KEYWORDS = (
    "calendar.google.com",
    "meet.google.com",
    "begin:vevent",
    "you have been invited",
    "joining info",
    "rsvp",
    "meeting link",
    "organizer",
    "when:",
)


@dataclass(frozen=True)
class ExtractedMeetingTask:
    """Normalized meeting invitation extracted from a Gmail message."""

    external_message_id: str
    title: str
    description: str
    scheduled_for: Optional[datetime]
    source: str
    attendees: List[str] = field(default_factory=list)
    organizer: Optional[str] = None
    calendar_event_link: Optional[str] = None
    raw_data: Dict[str, Any] = field(default_factory=dict)


def _decode_base64url(data: str) -> str:
    """Decode Gmail API base64url payloads safely."""
    if not data:
        return ""
    padded = data + "=" * (-len(data) % 4)
    raw_bytes = base64.urlsafe_b64decode(padded.encode("ascii"))
    return raw_bytes.decode("utf-8", errors="replace")


def _strip_html(raw_html: str) -> str:
    """Convert untrusted HTML snippets to plain text safely."""
    if not raw_html:
        return ""
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", raw_html)
    text = _HTML_TAG_PATTERN.sub(" ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def sanitize_event_url(raw_url: Optional[str]) -> Optional[str]:
    """Allow only safe external HTTPS URLs; block javascript:, data:, loopback, and private hosts."""
    if not raw_url or not isinstance(raw_url, str):
        return None
    candidate = raw_url.strip().rstrip(".,;:")
    parsed = urlparse(candidate)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        return None

    host = parsed.hostname.lower()
    if host in ("localhost", "localhost.localdomain") or host.endswith(".local"):
        return None

    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return None
    except ValueError:
        # Hostname is a domain name, not an IP literal.
        pass

    return candidate


def _pick_calendar_event_link(candidates: Iterable[str]) -> Optional[str]:
    """Select the highest-priority verified HTTPS calendar or conferencing link."""
    valid_urls: List[str] = []
    for raw in candidates:
        safe = sanitize_event_url(raw)
        if safe and safe not in valid_urls:
            valid_urls.append(safe)

    if not valid_urls:
        return None

    # Prefer Google Calendar event links first, then conferencing providers.
    for preferred_host in _CALENDAR_LINK_HOSTS:
        for url in valid_urls:
            host = (urlparse(url).hostname or "").lower()
            if host == preferred_host or host.endswith(f".{preferred_host}"):
                return url

    return valid_urls[0]


def _unfold_ics_lines(ics_text: str) -> List[str]:
    """Unfold RFC 5545 folded lines (CRLF/LF followed by single space or tab)."""
    normalized = ics_text.replace("\r\n", "\n").replace("\r", "\n")
    unfolded: List[str] = []
    for line in normalized.split("\n"):
        if line.startswith((" ", "\t")) and unfolded:
            unfolded[-1] += line[1:]
        else:
            unfolded.append(line)
    return unfolded


def _unescape_ics_text(value: str) -> str:
    return (
        value.replace("\\n", "\n")
        .replace("\\N", "\n")
        .replace("\\,", ",")
        .replace("\\;", ";")
        .replace("\\\\", "\\")
        .strip()
    )


def _parse_ics_datetime(raw_value: str) -> Optional[datetime]:
    """Parse RFC 5545 DTSTART/DTEND formats into naive UTC datetime."""
    value = raw_value.strip()
    if not value:
        return None

    formats = (
        ("%Y%m%dT%H%M%SZ", True),
        ("%Y%m%dT%H%M%S", False),
        ("%Y%m%d", False),
    )
    for fmt, is_utc in formats:
        try:
            dt = datetime.strptime(value, fmt)
            if is_utc:
                return dt.replace(tzinfo=timezone.utc).replace(tzinfo=None)
            return dt
        except ValueError:
            continue
    return None


def parse_ics_event(ics_text: str) -> Optional[Dict[str, Any]]:
    """Extract the first VEVENT block from an iCalendar (`.ics`) payload."""
    if not ics_text or "BEGIN:VEVENT" not in ics_text.upper():
        return None

    lines = _unfold_ics_lines(ics_text)
    in_vevent = False
    event: Dict[str, Any] = {"attendees": [], "urls": []}

    for line in lines:
        upper = line.upper().strip()
        if upper == "BEGIN:VEVENT":
            in_vevent = True
            continue
        if upper == "END:VEVENT":
            if in_vevent:
                break
            continue
        if not in_vevent or ":" not in line:
            continue

        prop_part, value = line.split(":", 1)
        prop_segments = prop_part.split(";")
        prop_name = prop_segments[0].upper().strip()
        params = {}
        for seg in prop_segments[1:]:
            if "=" in seg:
                k, v = seg.split("=", 1)
                params[k.upper().strip()] = v.strip().strip('"')

        if prop_name == "SUMMARY":
            event["summary"] = _unescape_ics_text(value)
        elif prop_name == "DESCRIPTION":
            event["description"] = _unescape_ics_text(value)
            event["urls"].extend(_URL_PATTERN.findall(event["description"]))
        elif prop_name == "DTSTART":
            event["dtstart"] = _parse_ics_datetime(value)
            event["dtstart_raw"] = value.strip()
            if "TZID" in params:
                event["tzid"] = params["TZID"]
        elif prop_name == "DTEND":
            event["dtend"] = _parse_ics_datetime(value)
            event["dtend_raw"] = value.strip()
        elif prop_name == "LOCATION":
            location = _unescape_ics_text(value)
            event["location"] = location
            event["urls"].extend(_URL_PATTERN.findall(location))
        elif prop_name in ("URL", "X-GOOGLE-CONFERENCE"):
            event["urls"].append(value.strip())
        elif prop_name == "UID":
            event["uid"] = value.strip()
        elif prop_name == "STATUS":
            event["ics_status"] = value.strip().upper()
        elif prop_name == "ORGANIZER":
            email_addr = re.sub(r"^mailto:", "", value.strip(), flags=re.IGNORECASE)
            cn = params.get("CN")
            event["organizer"] = f"{cn} <{email_addr}>" if cn and email_addr else (email_addr or cn)
        elif prop_name == "ATTENDEE":
            email_addr = re.sub(r"^mailto:", "", value.strip(), flags=re.IGNORECASE).lower()
            if email_addr and email_addr not in event["attendees"]:
                event["attendees"].append(email_addr)

    if not event.get("summary") and not event.get("dtstart"):
        return None
    return event


def _extract_headers(payload: Dict[str, Any]) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    for item in payload.get("headers") or []:
        name = str(item.get("name") or "").lower().strip()
        value = str(item.get("value") or "").strip()
        if name:
            headers[name] = value
    return headers


def _walk_mime_parts(payload: Dict[str, Any]) -> Dict[str, List[str]]:
    """Collect text/calendar, text/plain, and text/html bodies recursively from a Gmail message payload."""
    collected: Dict[str, List[str]] = {
        "ics": [],
        "plain": [],
        "html": [],
    }

    def _visit(part: Dict[str, Any]) -> None:
        mime_type = str(part.get("mimeType") or "").lower()
        filename = str(part.get("filename") or "").lower()
        body = part.get("body") or {}
        raw_data = body.get("data")

        if raw_data:
            decoded = _decode_base64url(str(raw_data))
            if (
                mime_type in ("text/calendar", "application/ics")
                or filename.endswith(".ics")
                or "BEGIN:VEVENT" in decoded.upper()
            ):
                collected["ics"].append(decoded)
            elif mime_type == "text/plain":
                collected["plain"].append(decoded)
            elif mime_type == "text/html":
                collected["html"].append(decoded)

        for child in part.get("parts") or []:
            if isinstance(child, dict):
                _visit(child)

    _visit(payload)
    return collected


def _clean_subject_title(subject: str) -> str:
    cleaned = subject.strip()
    lower = cleaned.lower()
    for prefix in _INVITE_SUBJECT_PREFIXES:
        if lower.startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()
            break
    # Strip trailing Google Calendar "@ Tue Nov 24, 2026 ..." suffix for crisp task titles.
    if " @ " in cleaned:
        cleaned = cleaned.split(" @ ", 1)[0].strip()
    return cleaned or "Untitled Meeting"


def _parse_email_datetime(headers: Dict[str, str], body_text: str) -> Optional[datetime]:
    """Fallback datetime extraction from 'When:' line or email Date header."""
    when_match = re.search(
        r"When:\s*([A-Za-z]{3},?\s+[A-Za-z]{3}\s+\d{1,2},?\s+\d{4}\s+\d{1,2}:\d{2}\s*(?:AM|PM)?)",
        body_text,
        flags=re.IGNORECASE,
    )
    if when_match:
        snippet = re.sub(r",", "", when_match.group(1)).strip()
        for fmt in ("%a %b %d %Y %I:%M %p", "%a %b %d %Y %I:%M%p", "%a %b %d %Y %H:%M"):
            try:
                return datetime.strptime(snippet, fmt)
            except ValueError:
                continue

    date_header = headers.get("date")
    if date_header:
        try:
            dt = parsedate_to_datetime(date_header)
            if dt.tzinfo is not None:
                return dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt
        except (TypeError, ValueError):
            pass

    return None


def _extract_header_attendees(headers: Dict[str, str]) -> List[str]:
    addresses: List[str] = []
    for key in ("to", "cc"):
        raw = headers.get(key)
        if not raw:
            continue
        for _, addr in getaddresses([raw]):
            normalized = addr.strip().lower()
            if normalized and "@" in normalized and normalized not in addresses:
                addresses.append(normalized)
    return addresses


def _is_likely_calendar_invite(
    headers: Dict[str, str],
    ics_event: Optional[Dict[str, Any]],
    plain_text: str,
) -> bool:
    if ics_event is not None:
        return True
    subject_lower = headers.get("subject", "").lower()
    if any(subject_lower.startswith(prefix) for prefix in _INVITE_SUBJECT_PREFIXES):
        return True
    combined_lower = f"{subject_lower}\n{plain_text.lower()}"
    return sum(1 for kw in _INVITE_BODY_KEYWORDS if kw in combined_lower) >= 2


def parse_gmail_invite_message(
    message: Dict[str, Any],
    extra_ics_payloads: Optional[List[str]] = None,
) -> Optional[ExtractedMeetingTask]:
    """Parse a Gmail API `messages.get(format='full')` dictionary into an ExtractedMeetingTask.

    Returns `None` if the message does not represent a calendar/meeting invitation.
    """
    message_id = str(message.get("id") or "").strip()
    if not message_id:
        return None

    payload = message.get("payload") or {}
    headers = _extract_headers(payload)
    parts = _walk_mime_parts(payload)

    ics_candidates = list(parts["ics"])
    if extra_ics_payloads:
        ics_candidates.extend(extra_ics_payloads)

    ics_event: Optional[Dict[str, Any]] = None
    for raw_ics in ics_candidates:
        parsed = parse_ics_event(raw_ics)
        if parsed is not None:
            ics_event = parsed
            break

    plain_body = "\n".join(parts["plain"]).strip()
    html_text = "\n".join(_strip_html(h) for h in parts["html"]).strip()
    body_text = plain_body or html_text or str(message.get("snippet") or "").strip()

    if not _is_likely_calendar_invite(headers, ics_event, body_text):
        return None

    # Gather URLs from ICS fields, plain text, and raw HTML hrefs.
    url_candidates: List[str] = []
    if ics_event:
        url_candidates.extend(ics_event.get("urls") or [])
    url_candidates.extend(_URL_PATTERN.findall(plain_body))
    for raw_html in parts["html"]:
        url_candidates.extend(_URL_PATTERN.findall(raw_html))

    calendar_event_link = _pick_calendar_event_link(url_candidates)

    subject = headers.get("subject", "")
    title = (
        (ics_event.get("summary") if ics_event else None)
        or _clean_subject_title(subject)
    )
    title = title[:500]

    scheduled_for = (
        ics_event.get("dtstart") if ics_event else None
    ) or _parse_email_datetime(headers, body_text)

    attendees: List[str] = []
    if ics_event:
        attendees.extend(ics_event.get("attendees") or [])
    for addr in _extract_header_attendees(headers):
        if addr not in attendees:
            attendees.append(addr)

    organizer = (ics_event.get("organizer") if ics_event else None) or headers.get("from")
    location = ics_event.get("location") if ics_event else None

    description_parts: List[str] = []
    if organizer:
        description_parts.append(f"Organizer: {organizer}")
    if attendees:
        description_parts.append(f"Attendees: {', '.join(attendees[:15])}")
    if location:
        description_parts.append(f"Location: {location}")
    if calendar_event_link:
        description_parts.append(f"Event Link: {calendar_event_link}")

    event_notes = (ics_event.get("description") if ics_event else None) or body_text
    if event_notes:
        description_parts.append(event_notes[:1200])

    description = "\n".join(description_parts).strip()

    source = "calendar" if ics_event is not None else "email"
    raw_data: Dict[str, Any] = {
        "gmail_message_id": message_id,
        "gmail_thread_id": message.get("threadId"),
        "subject": subject,
        "organizer": organizer,
        "attendees": attendees,
        "calendar_event_link": calendar_event_link,
        "location": location,
        "ics_uid": ics_event.get("uid") if ics_event else None,
        "ics_status": ics_event.get("ics_status") if ics_event else None,
        "start_time": scheduled_for.isoformat() + "Z" if scheduled_for else None,
        "end_time": (
            ics_event["dtend"].isoformat() + "Z"
            if ics_event and ics_event.get("dtend")
            else None
        ),
        "timezone": ics_event.get("tzid") if ics_event else None,
    }

    return ExtractedMeetingTask(
        external_message_id=message_id,
        title=title,
        description=description,
        scheduled_for=scheduled_for,
        source=source,
        attendees=attendees,
        organizer=organizer,
        calendar_event_link=calendar_event_link,
        raw_data=raw_data,
    )
