"""Unit and integration tests for AI email analysis, reply sending, Calendar insert, automatic payments, and inbox archiving."""

from __future__ import annotations

import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

# Allow running pure service unit tests even in minimal environments without requests installed.
if "requests" not in sys.modules:
    _fake_requests = types.ModuleType("requests")

    class _FakeRequestException(Exception):
        pass

    _fake_requests.RequestException = _FakeRequestException
    _fake_requests.Response = object
    _fake_requests.post = MagicMock()
    sys.modules["requests"] = _fake_requests

from app.services.email_analyzer import (  # noqa: E402
    EmailAnalysisConfigError,
    analyze_email_with_gemini,
)
from app.services.payment_executor import (  # noqa: E402
    PaymentGatewayNotConfiguredError,
    PaymentValidationError,
    PaymentExecutorService,
    _validate_public_https_url,
)


class SmartChiefOfStaffUnitTests(unittest.TestCase):
    def test_email_analyzer_requires_gemini_api_key_without_faking(self) -> None:
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}, clear=False):
            with self.assertRaises(EmailAnalysisConfigError):
                analyze_email_with_gemini(
                    subject="Can you attend tomorrow?",
                    sender="alex@partner.com",
                    body="Please RSVP for tomorrow at 3pm.",
                )

    def test_email_analyzer_parses_rsvp_reply_and_calendar_fields(self) -> None:
        fake_response = MagicMock()
        fake_response.status_code = 200
        fake_response.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": (
                                    '{"category":"meeting_rsvp",'
                                    '"summary":"Alex invited you to the Q4 Roadmap sync and requested an RSVP.",'
                                    '"recommended_action":"Send RSVP confirmation to Alex and add Q4 Roadmap to Google Calendar?",'
                                    '"requires_reply":true,'
                                    '"draft_reply":{"to":"Alex <alex@partner.com>","subject":"Re: Q4 Roadmap\\r\\nBcc: evil@x.com","body":"Hi Alex,\\n\\nI will attend. Looking forward to it."},'
                                    '"requires_payment":false,'
                                    '"payment":{"amount":0,"currency":"INR","payee_name":"","payee_email":"","payee_upi_id":"billing@okaxis","payee_bank_account":"123456789012","payee_ifsc":"hdfc0001234","invoice_number":"","due_date":"","payment_reference":"","payment_url":"javascript:alert(1)"},'
                                    '"requires_calendar":true,'
                                    '"requires_rsvp":true,'
                                    '"calendar_event":{"title":"Q4 Roadmap Sync","start_iso":"2026-11-26T15:00:00Z","end_iso":"2026-11-26T16:00:00Z","location":"https://meet.google.com/abc-defg-hij","description":"Roadmap discussion","attendees":["alex@partner.com","not-an-email"]},'
                                    '"confidence":"high"}'
                                )
                            }
                        ]
                    }
                }
            ]
        }

        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key-123", "GMAIL_PROCESSED_LABEL": "Joshu/Processed"}, clear=False):
            with patch("app.services.email_analyzer.requests.post", return_value=fake_response):
                result = analyze_email_with_gemini(
                    subject="Q4 Roadmap",
                    sender="Alex <alex@partner.com>",
                    body="Please RSVP for Nov 26 at 15:00 UTC.",
                    user_name="Joshu",
                    user_email="joshu@example.com",
                )

        self.assertEqual(result["category"], "meeting_rsvp")
        self.assertTrue(result["requires_rsvp"])
        self.assertTrue(result["requires_reply"])
        self.assertTrue(result["requires_calendar"])
        self.assertEqual(result["draft_reply"]["to"], "alex@partner.com")
        # CRLF header injection stripped to single line
        self.assertNotIn("\r", result["draft_reply"]["subject"])
        self.assertNotIn("\n", result["draft_reply"]["subject"])
        # Unsafe javascript: URL stripped; Indian payment coordinates normalized
        self.assertEqual(result["payment"]["payment_url"], "")
        self.assertEqual(result["payment"]["payee_upi_id"], "billing@okaxis")
        self.assertEqual(result["payment"]["payee_bank_account"], "123456789012")
        self.assertEqual(result["payment"]["payee_ifsc"], "HDFC0001234")
        self.assertEqual(result["calendar_event"]["start_iso"], "2026-11-26T15:00:00Z")
        self.assertEqual(result["calendar_event"]["attendees"], ["alex@partner.com"])
        self.assertEqual(result["target_folder"], "Joshu/Processed")

    def test_payment_executor_requires_configured_gateway_and_enforces_limits_and_ssrf(self) -> None:
        executor = PaymentExecutorService()

        # Missing gateway credentials -> honest error, never fake success
        with patch.dict(
            os.environ,
            {
                "RAZORPAY_KEY_ID": "",
                "RAZORPAY_KEY_SECRET": "",
                "RAZORPAYX_ACCOUNT_NUMBER": "",
                "STRIPE_SECRET_KEY": "",
                "PAYMENT_API_URL": "",
                "PAYMENT_API_KEY": "",
            },
            clear=False,
        ):
            with self.assertRaises(PaymentGatewayNotConfiguredError):
                executor.execute_payment(
                    task_id="task-1",
                    user_email="ceo@company.com",
                    amount=1200.0,
                    currency="INR",
                    payee_name="Acme India Pvt Ltd",
                )

        # Exceeding max auto payment safety ceiling -> validation error
        with patch.dict(os.environ, {"PAYMENT_MAX_AUTO_AMOUNT": "500"}, clear=False):
            with self.assertRaises(PaymentValidationError):
                executor.execute_payment(
                    task_id="task-2",
                    user_email="ceo@company.com",
                    amount=750.0,
                    currency="INR",
                    payee_name="Acme India Pvt Ltd",
                )

        # SSRF protection on custom payment gateway URL
        with self.assertRaises(PaymentValidationError):
            _validate_public_https_url("http://api.payments.example/pay")
        with self.assertRaises(PaymentValidationError):
            _validate_public_https_url("https://127.0.0.1/pay")
        with self.assertRaises(PaymentValidationError):
            _validate_public_https_url("https://localhost/pay")

    def test_payment_executor_executes_razorpayx_upi_and_imps_payouts(self) -> None:
        executor = PaymentExecutorService()
        fake_rzp_resp = MagicMock()
        fake_rzp_resp.status_code = 200
        fake_rzp_resp.content = b'{"id": "pout_india_001", "status": "processing", "utr": "432198765432"}'
        fake_rzp_resp.json.return_value = {
            "id": "pout_india_001",
            "status": "processing",
            "utr": "432198765432",
        }

        rzp_env = {
            "RAZORPAY_KEY_ID": "rzp_example_id",
            "RAZORPAY_KEY_SECRET": "rzp_example_secret",
            "RAZORPAYX_ACCOUNT_NUMBER": "2323230012345678",
            "RAZORPAYX_PAYOUT_MODE": "IMPS",
            "RAZORPAYX_PAYOUT_PURPOSE": "payout",
            "RAZORPAYX_PAYEE_FUND_ACCOUNTS_JSON": "",
            "PAYMENT_MAX_AUTO_AMOUNT": "50000",
        }

        # 1. UPI payout
        with patch.dict(os.environ, rzp_env, clear=False):
            with patch("app.services.payment_executor.requests.post", return_value=fake_rzp_resp) as mock_post:
                res_upi = executor.execute_payment(
                    task_id="task-upi-1",
                    user_email="founder@startup.in",
                    amount=2500.75,
                    currency="INR",
                    payee_name="Zoho Corp",
                    payee_email="billing@zoho.in",
                    payee_upi_id="zoho.billing@icici",
                    invoice_number="INV-IN-101",
                )

        self.assertTrue(res_upi["executed"])
        self.assertEqual(res_upi["provider"], "razorpayx_upi")
        self.assertEqual(res_upi["payment_id"], "pout_india_001")
        self.assertEqual(res_upi["currency"], "INR")
        upi_kwargs = mock_post.call_args.kwargs
        self.assertEqual(upi_kwargs["auth"], ("rzp_example_id", "rzp_example_secret"))
        self.assertEqual(upi_kwargs["headers"]["X-Payout-Idempotency"], "joshu-pay-task-upi-1")
        self.assertEqual(upi_kwargs["json"]["amount"], 250075)
        self.assertEqual(upi_kwargs["json"]["mode"], "UPI")
        self.assertEqual(upi_kwargs["json"]["fund_account"]["account_type"], "vpa")
        self.assertEqual(upi_kwargs["json"]["fund_account"]["vpa"]["address"], "zoho.billing@icici")

        # 2. Bank account + IFSC (IMPS) payout
        with patch.dict(os.environ, rzp_env, clear=False):
            with patch("app.services.payment_executor.requests.post", return_value=fake_rzp_resp) as mock_post:
                res_imps = executor.execute_payment(
                    task_id="task-imps-2",
                    user_email="founder@startup.in",
                    amount=14500.0,
                    currency="INR",
                    payee_name="Bengaluru Design Studio",
                    payee_bank_account="50100123456789",
                    payee_ifsc="hdfc0001234",
                    invoice_number="INV-IN-202",
                )

        self.assertTrue(res_imps["executed"])
        self.assertEqual(res_imps["provider"], "razorpayx_imps")
        imps_body = mock_post.call_args.kwargs["json"]
        self.assertEqual(imps_body["amount"], 1450000)
        self.assertEqual(imps_body["mode"], "IMPS")
        self.assertEqual(imps_body["fund_account"]["account_type"], "bank_account")
        self.assertEqual(imps_body["fund_account"]["bank_account"]["ifsc"], "HDFC0001234")
        self.assertEqual(imps_body["fund_account"]["bank_account"]["account_number"], "50100123456789")

        # 3. Validation failures: non-INR, invalid UPI, invalid IFSC, missing destination
        with patch.dict(os.environ, rzp_env, clear=False):
            with self.assertRaises(PaymentValidationError):
                executor.execute_payment(
                    task_id="task-bad-curr",
                    user_email="founder@startup.in",
                    amount=100.0,
                    currency="USD",
                    payee_name="Vendor",
                    payee_upi_id="vendor@icici",
                )
            with self.assertRaises(PaymentValidationError):
                executor.execute_payment(
                    task_id="task-bad-upi",
                    user_email="founder@startup.in",
                    amount=100.0,
                    currency="INR",
                    payee_name="Vendor",
                    payee_upi_id="not-a-valid-upi",
                )
            with self.assertRaises(PaymentValidationError):
                executor.execute_payment(
                    task_id="task-bad-ifsc",
                    user_email="founder@startup.in",
                    amount=100.0,
                    currency="INR",
                    payee_name="Vendor",
                    payee_bank_account="50100123456789",
                    payee_ifsc="BADIFSC",
                )
            with self.assertRaises(PaymentValidationError):
                executor.execute_payment(
                    task_id="task-no-dest",
                    user_email="founder@startup.in",
                    amount=100.0,
                    currency="INR",
                    payee_name="Vendor",
                )

    def test_payment_executor_executes_stripe_payment_intent_with_idempotency(self) -> None:
        executor = PaymentExecutorService()
        fake_stripe_resp = MagicMock()
        fake_stripe_resp.status_code = 200
        fake_stripe_resp.content = b'{"id": "pi_example_12345", "status": "succeeded"}'
        fake_stripe_resp.json.return_value = {"id": "pi_example_12345", "status": "succeeded"}

        with patch.dict(
            os.environ,
            {
                "RAZORPAY_KEY_ID": "",
                "RAZORPAY_KEY_SECRET": "",
                "RAZORPAYX_ACCOUNT_NUMBER": "",
                "STRIPE_SECRET_KEY": "stripe_example_placeholder",
                "STRIPE_CUSTOMER_ID": "cus_123",
                "STRIPE_DEFAULT_PAYMENT_METHOD_ID": "pm_123",
                "STRIPE_PAYEE_ACCOUNTS_JSON": "",
            },
            clear=False,
        ):
            with patch("app.services.payment_executor.requests.post", return_value=fake_stripe_resp) as mock_post:
                res = executor.execute_payment(
                    task_id="task-pay-99",
                    user_email="ceo@company.com",
                    amount=249.50,
                    currency="USD",
                    payee_name="Acme Cloud",
                    payee_email="billing@acme.com",
                    invoice_number="INV-2026-09",
                )

        self.assertTrue(res["executed"])
        self.assertEqual(res["provider"], "stripe")
        self.assertEqual(res["payment_id"], "pi_example_12345")
        self.assertEqual(res["amount"], 249.5)
        call_kwargs = mock_post.call_args.kwargs
        self.assertEqual(call_kwargs["headers"]["Idempotency-Key"], "joshu-pay-task-pay-99")
        self.assertEqual(call_kwargs["data"]["amount"], "24950")
        self.assertEqual(call_kwargs["data"]["confirm"], "true")
        self.assertEqual(call_kwargs["data"]["off_session"], "true")


if __name__ == "__main__":
    unittest.main()
