"""Pure standard-library unit tests for Gmail/ICS calendar invitation parsing.

Runnable directly with `python3 -m unittest backend/tests/test_invite_parser.py`.
"""

from __future__ import annotations

import base64
import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.invite_parser import (  # noqa: E402
    parse_gmail_invite_message,
    parse_ics_event,
    sanitize_event_url,
)


def _b64url(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


class InviteParserTests(unittest.TestCase):
    def test_parses_rfc5545_ics_attachment_with_folded_lines_and_attendees(self) -> None:
        ics = "\r\n".join(
            [
                "BEGIN:VCALENDAR",
                "VERSION:2.0",
                "BEGIN:VEVENT",
                "UID:evt-q4-board-sync@google.com",
                "SUMMARY:Q4 Board Strategy",
                "  Review",
                "DTSTART:20261201T153000Z",
                "DTEND:20261201T163000Z",
                'ORGANIZER;CN="Sarah Chen":mailto:sarah@acme.com',
                "ATTENDEE;CN=Alex:mailto:alex@acme.com",
                "ATTENDEE;CN=Jordan:mailto:JORDAN@acme.com",
                "X-GOOGLE-CONFERENCE:https://meet.google.com/abc-defg-hij",
                "DESCRIPTION:Quarterly review agenda\\nJoin here: https://calendar.google.com/calendar/event?eid=12345",
                "LOCATION:https://meet.google.com/abc-defg-hij",
                "STATUS:CONFIRMED",
                "END:VEVENT",
                "END:VCALENDAR",
            ]
        )

        message = {
            "id": "gmail-msg-001",
            "threadId": "thread-001",
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Invitation: Q4 Board Strategy Review @ Tue Dec 1, 2026"},
                    {"name": "From", "value": "Sarah Chen <sarah@acme.com>"},
                    {"name": "To", "value": "alex@acme.com"},
                ],
                "parts": [
                    {
                        "mimeType": "text/plain",
                        "body": {"data": _b64url("You have been invited to Q4 Board Strategy Review.")},
                    },
                    {
                        "mimeType": "text/calendar",
                        "filename": "invite.ics",
                        "body": {"data": _b64url(ics)},
                    },
                ],
            },
        }

        task = parse_gmail_invite_message(message)
        self.assertIsNotNone(task)
        assert task is not None
        self.assertEqual(task.external_message_id, "gmail-msg-001")
        self.assertEqual(task.source, "calendar")
        self.assertEqual(task.title, "Q4 Board Strategy Review")
        self.assertEqual(task.scheduled_for, datetime(2026, 12, 1, 15, 30, 0))
        self.assertEqual(task.attendees, ["alex@acme.com", "jordan@acme.com"])
        self.assertEqual(task.organizer, "Sarah Chen <sarah@acme.com>")
        # Google Calendar link takes priority over Meet link.
        self.assertEqual(
            task.calendar_event_link,
            "https://calendar.google.com/calendar/event?eid=12345",
        )
        self.assertEqual(task.raw_data["ics_uid"], "evt-q4-board-sync@google.com")
        self.assertEqual(task.raw_data["end_time"], "2026-12-01T16:30:00Z")

    def test_parses_email_invite_without_ics_attachment(self) -> None:
        body = (
            "You have been invited to the following event.\n"
            "When: Wed, Dec 2, 2026 2:00 PM\n"
            "Joining info: https://meet.google.com/xyz-uvwx-rst\n"
        )
        message = {
            "id": "gmail-msg-002",
            "threadId": "thread-002",
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Invitation: Product Launch Sync @ Wed Dec 2, 2026"},
                    {"name": "From", "value": "pm@company.com"},
                    {"name": "To", "value": "founder@company.com, eng@company.com"},
                ],
                "parts": [
                    {"mimeType": "text/plain", "body": {"data": _b64url(body)}},
                ],
            },
        }

        task = parse_gmail_invite_message(message)
        self.assertIsNotNone(task)
        assert task is not None
        self.assertEqual(task.source, "email")
        self.assertEqual(task.title, "Product Launch Sync")
        self.assertEqual(task.scheduled_for, datetime(2026, 12, 2, 14, 0, 0))
        self.assertEqual(task.attendees, ["founder@company.com", "eng@company.com"])
        self.assertEqual(task.calendar_event_link, "https://meet.google.com/xyz-uvwx-rst")

    def test_ignores_regular_non_invite_email(self) -> None:
        message = {
            "id": "gmail-msg-003",
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Weekly Newsletter"},
                    {"name": "From", "value": "news@example.com"},
                ],
                "parts": [
                    {
                        "mimeType": "text/plain",
                        "body": {"data": _b64url("Here are the top headlines this week.")},
                    }
                ],
            },
        }
        self.assertIsNone(parse_gmail_invite_message(message))

    def test_sanitize_event_url_blocks_unsafe_schemes_and_private_hosts(self) -> None:
        self.assertIsNone(sanitize_event_url("javascript:alert(1)"))
        self.assertIsNone(sanitize_event_url("data:text/html,<script>alert(1)</script>"))
        self.assertIsNone(sanitize_event_url("http://calendar.google.com/insecure"))
        self.assertIsNone(sanitize_event_url("https://localhost/admin"))
        self.assertIsNone(sanitize_event_url("https://169.254.169.254/latest/meta-data"))
        self.assertIsNone(sanitize_event_url("https://192.168.1.10/internal"))
        self.assertEqual(
            sanitize_event_url("https://calendar.google.com/calendar/event?eid=abc."),
            "https://calendar.google.com/calendar/event?eid=abc",
        )

    def test_parse_ics_event_handles_tzid_and_escaped_commas(self) -> None:
        ics = "\n".join(
            [
                "BEGIN:VCALENDAR",
                "BEGIN:VEVENT",
                "SUMMARY:Design\\, Architecture\\; Review",
                "DTSTART;TZID=America/Los_Angeles:20261205T090000",
                "END:VEVENT",
                "END:VCALENDAR",
            ]
        )
        parsed = parse_ics_event(ics)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["summary"], "Design, Architecture; Review")
        self.assertEqual(parsed["dtstart"], datetime(2026, 12, 5, 9, 0, 0))
        self.assertEqual(parsed["tzid"], "America/Los_Angeles")


if __name__ == "__main__":
    unittest.main()
