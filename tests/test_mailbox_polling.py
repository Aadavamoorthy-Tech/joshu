"""Unit tests for universal IMAP polling, Google OAuth flow, SSRF guards, and session isolation."""

from __future__ import annotations

import base64
import os
import socket
import unittest
from email.message import EmailMessage
from unittest.mock import patch

from preview_server.google_oauth_service import (
    build_google_authorization_url,
    parse_gmail_api_message_to_task,
)
from preview_server.imap_service import (
    ImapValidationError,
    detect_imap_provider,
    parse_raw_email_bytes,
    validate_imap_target,
)
from preview_server.session_store import SessionManager


def _fake_public_resolver(host: str, port: int):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]


def _fake_private_resolver(host: str, port: int):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.42", port))]


class TestProviderDetectionAndSsrf(unittest.TestCase):
    def test_detects_major_email_providers(self) -> None:
        self.assertEqual(detect_imap_provider("user@gmail.com").host, "imap.gmail.com")
        self.assertEqual(detect_imap_provider("exec@outlook.com").host, "outlook.office365.com")
        self.assertEqual(detect_imap_provider("ops@yahoo.com").host, "imap.mail.yahoo.com")
        self.assertEqual(detect_imap_provider("ceo@icloud.com").host, "imap.mail.me.com")
        self.assertEqual(detect_imap_provider("team@fastmail.com").host, "imap.fastmail.com")
        self.assertEqual(detect_imap_provider("sales@zoho.com").host, "imap.zoho.com")

        custom = detect_imap_provider("founder@northstar-corp.io")
        self.assertFalse(custom.detected)
        self.assertEqual(custom.host, "imap.northstar-corp.io")

    def test_ssrf_blocks_private_loopback_and_non_993_ports(self) -> None:
        for bad_host in (
            "localhost",
            "127.0.0.1",
            "169.254.169.254",
            "10.0.0.1",
            "192.168.1.1",
            "metadata.google.internal",
            "mail.corp.local",
            "bad host name",
        ):
            with self.assertRaises(ImapValidationError):
                validate_imap_target(bad_host, 993, resolver=_fake_public_resolver)

        # Reject private DNS resolution (DNS rebinding / internal CNAME protection)
        with self.assertRaises(ImapValidationError):
            validate_imap_target("imap.example.com", 993, resolver=_fake_private_resolver)

        # Reject plaintext port 143 or arbitrary port
        with self.assertRaises(ImapValidationError):
            validate_imap_target("imap.example.com", 143, resolver=_fake_public_resolver)

        # Allow public domain on IMAPS 993
        host, port = validate_imap_target("imap.example.com", 993, resolver=_fake_public_resolver)
        self.assertEqual((host, port), ("imap.example.com", 993))


class TestEmailParsingAndSanitization(unittest.TestCase):
    def test_parses_rfc822_ics_calendar_invite(self) -> None:
        msg = EmailMessage()
        msg["Message-ID"] = "<invite-101@acme.com>"
        msg["Subject"] = "Invitation: Series A Partner Sync"
        msg["From"] = "Partner <partner@acme.com>"
        msg["To"] = "founder@startup.io"
        msg["Date"] = "Tue, 24 Nov 2026 10:00:00 +0000"
        msg.set_content("Please join our Series A review.")

        ics = "\r\n".join(
            [
                "BEGIN:VCALENDAR",
                "VERSION:2.0",
                "BEGIN:VEVENT",
                "UID:evt-101@acme.com",
                "SUMMARY:Series A Partner Sync",
                "DTSTART:20261126T153000Z",
                "DTEND:20261126T161500Z",
                "ORGANIZER:mailto:partner@acme.com",
                "ATTENDEE:mailto:founder@startup.io",
                "ATTENDEE:mailto:cfo@startup.io",
                "URL:https://meet.google.com/abc-defg-hij",
                "DESCRIPTION:Review quarterly metrics and term sheet.",
                "END:VEVENT",
                "END:VCALENDAR",
            ]
        )
        msg.add_attachment(
            ics.encode("utf-8"),
            maintype="text",
            subtype="calendar",
            filename="invite.ics",
        )

        task = parse_raw_email_bytes(msg.as_bytes(), "founder@startup.io", "101")
        self.assertEqual(task["source"], "calendar")
        self.assertEqual(task["title"], "Series A Partner Sync")
        self.assertEqual(task["scheduled_for"], "2026-11-26T15:30:00Z")
        self.assertEqual(task["calendar_event_link"], "https://meet.google.com/abc-defg-hij")
        self.assertIn("founder@startup.io", task["attendees"])
        self.assertEqual(task["status"], "pending")

    def test_sanitizes_untrusted_html_and_blocks_unsafe_links(self) -> None:
        msg = EmailMessage()
        msg["Message-ID"] = "<email-202@vendor.io>"
        msg["Subject"] = "Invoice #4821"
        msg["From"] = "billing@vendor.io"
        msg["To"] = "founder@startup.io"
        msg["Date"] = "Tue, 24 Nov 2026 11:00:00 +0000"
        msg.add_alternative(
            '<html><body><script>alert("xss")</script><p>Invoice ready</p>'
            '<a href="javascript:alert(1)">Bad</a>'
            '<a href="https://127.0.0.1/admin">Local</a></body></html>',
            subtype="html",
        )

        task = parse_raw_email_bytes(msg.as_bytes(), "founder@startup.io", "202")
        self.assertEqual(task["source"], "email")
        self.assertEqual(task["title"], "Invoice #4821")
        self.assertNotIn("<script>", task["description"])
        self.assertNotIn("alert(", task["description"])
        self.assertIn("Invoice ready", task["description"])
        self.assertIsNone(task["calendar_event_link"])

    def test_parses_gmail_api_regular_inbox_message(self) -> None:
        raw_text = base64.urlsafe_b64encode(b"Please review the Q1 hiring plan.").decode("ascii")
        gmail_msg = {
            "id": "gm-999",
            "threadId": "thr-999",
            "snippet": "Please review the Q1 hiring plan.",
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Q1 Hiring Plan"},
                    {"name": "From", "value": "vp-eng@company.com"},
                    {"name": "To", "value": "ceo@company.com"},
                    {"name": "Date", "value": "Tue, 24 Nov 2026 12:00:00 +0000"},
                ],
                "parts": [
                    {"mimeType": "text/plain", "body": {"data": raw_text}},
                ],
            },
        }
        task = parse_gmail_api_message_to_task(gmail_msg, "ceo@company.com")
        self.assertIsNotNone(task)
        assert task is not None
        self.assertEqual(task["title"], "Q1 Hiring Plan")
        self.assertEqual(task["source"], "email")
        self.assertEqual(task["account_email"], "ceo@company.com")


class TestGoogleOAuthAndSessionIsolation(unittest.TestCase):
    def test_google_auth_url_always_prompts_account_selection(self) -> None:
        with patch.dict(
            os.environ,
            {
                "GOOGLE_CLIENT_ID": "test-client-id.apps.googleusercontent.com",
                "GOOGLE_CLIENT_SECRET": "test-client-secret",
            },
            clear=False,
        ):
            url, redirect_uri = build_google_authorization_url("http://localhost:3000", "state-123")
            self.assertEqual(redirect_uri, "http://localhost:3000/auth/google/callback")
            self.assertIn("prompt=select_account+consent", url)
            self.assertIn("gmail.readonly", url)
            self.assertIn("access_type=offline", url)

    def test_session_isolation_dedup_and_credential_wipe_on_signout(self) -> None:
        def fake_imap_fetcher(email_address, password, imap_host, imap_port=993, max_messages=20):
            return [
                {
                    "id": f"task-{email_address}-1",
                    "account_email": email_address,
                    "external_message_id": f"ext-{email_address}-1",
                    "title": f"Inbox item for {email_address}",
                    "description": "Real polled email",
                    "snippet": "Real polled email",
                    "scheduled_for": "2026-11-25T10:00:00Z",
                    "source": "email",
                    "is_meeting_invite": False,
                    "status": "pending",
                    "organizer": "sender@external.com",
                    "attendees": [email_address],
                    "calendar_event_link": None,
                    "raw_data": {},
                    "created_at": "2026-11-24T10:00:00Z",
                    "updated_at": "2026-11-24T10:00:00Z",
                    "approved_at": None,
                    "rejected_at": None,
                    "rejection_reason": None,
                    "approved_by_user": False,
                }
            ]

        mgr = SessionManager(imap_fetcher=fake_imap_fetcher, enable_background_threads=False)
        with patch("preview_server.session_store.validate_imap_target", return_value=("imap.gmail.com", 993)):
            tok_a, sess_a, cnt_a = mgr.sign_in_imap("alice@gmail.com", "app-pass-a")
            tok_b, sess_b, cnt_b = mgr.sign_in_imap("bob@gmail.com", "app-pass-b")

        self.assertEqual(cnt_a, 1)
        self.assertEqual(cnt_b, 1)

        # Account B cannot approve Account A's task
        task_a_id = mgr.list_tasks(tok_a)["tasks"][0]["id"]
        _, outcome = mgr.decide_task(tok_b, task_a_id, "approve")
        self.assertEqual(outcome, "not_found")

        # Account A approves its task; re-polling does not duplicate or overwrite approval
        approved_task, outcome = mgr.decide_task(tok_a, task_a_id, "approve")
        self.assertEqual(outcome, "ok")
        self.assertEqual(approved_task["status"], "approved")

        _, new_created = mgr.sync_now(tok_a)
        self.assertEqual(new_created, 0)
        self.assertEqual(mgr.list_tasks(tok_a)["tasks"][0]["status"], "approved")

        # Sign out wipes session and credentials
        self.assertTrue(mgr.sign_out(tok_a))
        self.assertIsNone(mgr.get_session(tok_a))
        self.assertIsNone(sess_a._imap_password)
        self.assertEqual(len(sess_a.tasks), 0)
        # Account B remains unaffected
        self.assertIsNotNone(mgr.get_session(tok_b))


if __name__ == "__main__":
    unittest.main()
