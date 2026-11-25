"""Real automatic payment execution service (RazorpayX India UPI/IMPS/NEFT, Stripe, or HTTPS gateway)."""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import re
import socket
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import requests

logger = logging.getLogger("joshu.payment_executor")

DEFAULT_MAX_AUTO_AMOUNT = 50000.0
RAZORPAY_API_BASE = "https://api.razorpay.com/v1"
STRIPE_API_BASE = "https://api.stripe.com/v1"

_ISO_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_UPI_ID_RE = re.compile(r"^[A-Za-z0-9._\-]{2,256}@[A-Za-z]{2,64}$")
_IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
_BANK_ACCT_RE = re.compile(r"^[0-9]{6,20}$")
_ALLOWED_RAZORPAY_MODES = {"UPI", "IMPS", "NEFT", "RTGS"}
_ZERO_DECIMAL_CURRENCIES = {
    "BIF", "CLP", "DJF", "GNF", "JPY", "KMF", "KRW", "MGA",
    "PYG", "RWF", "UGX", "VND", "VUV", "XAF", "XOF", "XPF",
}


class PaymentExecutionError(RuntimeError):
    """Base error raised when executing an automatic payment fails."""


class PaymentGatewayNotConfiguredError(PaymentExecutionError):
    """Raised when no real payment gateway credentials are configured in backend/.env."""


class PaymentValidationError(PaymentExecutionError):
    """Raised when payment amount, currency, destination, or ceiling validation fails."""


def _clean_env(name: str) -> str:
    val = (os.getenv(name) or "").strip()
    if not val:
        return ""
    upper = val.upper()
    if any(upper.startswith(p) for p in ("YOUR_", "REPLACE_", "<")):
        return ""
    return val


def is_payment_gateway_configured() -> bool:
    """Return True if RazorpayX (India), Stripe, or a custom HTTPS payment gateway is configured."""
    has_razorpayx = bool(
        _clean_env("RAZORPAY_KEY_ID")
        and _clean_env("RAZORPAY_KEY_SECRET")
        and _clean_env("RAZORPAYX_ACCOUNT_NUMBER")
    )
    has_stripe = bool(_clean_env("STRIPE_SECRET_KEY"))
    has_custom = bool(_clean_env("PAYMENT_API_URL") and _clean_env("PAYMENT_API_KEY"))
    return has_razorpayx or has_stripe or has_custom


def get_max_auto_payment_amount() -> float:
    raw = os.getenv("PAYMENT_MAX_AUTO_AMOUNT", str(DEFAULT_MAX_AUTO_AMOUNT)).strip()
    try:
        limit = float(raw)
        return max(1.0, limit)
    except ValueError:
        return DEFAULT_MAX_AUTO_AMOUNT


def _validate_public_https_url(url: str) -> str:
    """Validate that a configured custom payment API URL uses HTTPS and resolves to public IPs."""
    parsed = urlparse(url)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise PaymentValidationError("PAYMENT_API_URL must be a valid https:// URL.")

    host = parsed.hostname.lower().strip(".")
    if host in ("localhost", "127.0.0.1", "0.0.0.0") or host.endswith((".local", ".internal")):
        raise PaymentValidationError("PAYMENT_API_URL cannot point to a local or internal host.")

    try:
        infos = socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise PaymentExecutionError("Could not resolve PAYMENT_API_URL host.") from exc

    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise PaymentValidationError("PAYMENT_API_URL must resolve to a public IP address.")

    return url


def _to_minor_units(amount: float, currency: str) -> int:
    if currency in _ZERO_DECIMAL_CURRENCIES:
        return int(round(amount))
    return int(round(amount * 100))


def _load_json_map_env(env_name: str) -> Dict[str, str]:
    raw = _clean_env(env_name)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return {str(k).strip().lower(): str(v).strip() for k, v in parsed.items() if k and v}
    except Exception:
        logger.warning("Invalid JSON in %s; ignoring mapping", env_name)
    return {}


class PaymentExecutorService:
    """Executes real automatic payments via RazorpayX (India), Stripe, or a custom HTTPS gateway."""

    def execute_payment(
        self,
        *,
        task_id: str,
        user_email: str,
        amount: float,
        currency: str,
        payee_name: str,
        payee_email: str = "",
        payee_upi_id: str = "",
        payee_bank_account: str = "",
        payee_ifsc: str = "",
        payment_mode: str = "",
        invoice_number: str = "",
        payment_reference: str = "",
    ) -> Dict[str, Any]:
        if not isinstance(amount, (int, float)) or amount <= 0:
            raise PaymentValidationError("Payment amount must be greater than zero.")

        max_limit = get_max_auto_payment_amount()
        if amount > max_limit:
            raise PaymentValidationError(
                f"Payment amount ({amount:.2f}) exceeds PAYMENT_MAX_AUTO_AMOUNT safety limit ({max_limit:.2f})."
            )

        norm_currency = str(currency or "INR").strip().upper()
        if not _ISO_CURRENCY_RE.match(norm_currency):
            raise PaymentValidationError("Currency must be a valid 3-letter ISO code (e.g. INR, USD, EUR).")

        clean_payee = str(payee_name or payee_email or "Vendor").strip()[:160]
        clean_payee_email = str(payee_email or "").strip().lower()[:160]
        clean_upi = str(payee_upi_id or "").strip().lower()
        clean_bank_acct = re.sub(r"\s+", "", str(payee_bank_account or "").strip())
        clean_ifsc = str(payee_ifsc or "").strip().upper()
        idempotency_key = f"joshu-pay-{task_id}"

        # Provider 1: RazorpayX Payouts (India - UPI / IMPS / NEFT / RTGS)
        rzp_key_id = _clean_env("RAZORPAY_KEY_ID")
        rzp_key_secret = _clean_env("RAZORPAY_KEY_SECRET")
        rzp_account_number = _clean_env("RAZORPAYX_ACCOUNT_NUMBER")
        if rzp_key_id and rzp_key_secret and rzp_account_number:
            return self._execute_razorpayx_payout(
                key_id=rzp_key_id,
                key_secret=rzp_key_secret,
                account_number=rzp_account_number,
                task_id=task_id,
                idempotency_key=idempotency_key,
                user_email=user_email,
                amount=float(amount),
                currency=norm_currency,
                payee_name=clean_payee,
                payee_email=clean_payee_email,
                payee_upi_id=clean_upi,
                payee_bank_account=clean_bank_acct,
                payee_ifsc=clean_ifsc,
                payment_mode=payment_mode,
                invoice_number=invoice_number,
                payment_reference=payment_reference,
            )

        # Provider 2: Stripe (Global)
        stripe_key = _clean_env("STRIPE_SECRET_KEY")
        if stripe_key:
            return self._execute_stripe_payment(
                stripe_key=stripe_key,
                task_id=task_id,
                idempotency_key=idempotency_key,
                user_email=user_email,
                amount=float(amount),
                currency=norm_currency,
                payee_name=clean_payee,
                payee_email=clean_payee_email,
                invoice_number=invoice_number,
                payment_reference=payment_reference,
            )

        # Provider 3: Custom HTTPS Payment / Banking Gateway API
        custom_url = _clean_env("PAYMENT_API_URL")
        custom_key = _clean_env("PAYMENT_API_KEY")
        if custom_url and custom_key:
            return self._execute_custom_gateway_payment(
                gateway_url=custom_url,
                api_key=custom_key,
                task_id=task_id,
                idempotency_key=idempotency_key,
                user_email=user_email,
                amount=float(amount),
                currency=norm_currency,
                payee_name=clean_payee,
                payee_email=clean_payee_email,
                payee_upi_id=clean_upi,
                payee_bank_account=clean_bank_acct,
                payee_ifsc=clean_ifsc,
                invoice_number=invoice_number,
                payment_reference=payment_reference,
            )

        raise PaymentGatewayNotConfiguredError(
            "Automatic payment gateway is not configured in backend/.env. "
            "For India, configure RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET, and RAZORPAYX_ACCOUNT_NUMBER "
            "(for UPI / IMPS / NEFT payouts), or configure PAYMENT_API_URL + PAYMENT_API_KEY, then restart the backend."
        )

    def _execute_razorpayx_payout(
        self,
        *,
        key_id: str,
        key_secret: str,
        account_number: str,
        task_id: str,
        idempotency_key: str,
        user_email: str,
        amount: float,
        currency: str,
        payee_name: str,
        payee_email: str,
        payee_upi_id: str,
        payee_bank_account: str,
        payee_ifsc: str,
        payment_mode: str,
        invoice_number: str,
        payment_reference: str,
    ) -> Dict[str, Any]:
        if currency != "INR":
            raise PaymentValidationError(
                f"RazorpayX payouts require INR currency (received {currency}). Update currency to INR before approving."
            )

        paise_amount = _to_minor_units(amount, "INR")
        purpose = (_clean_env("RAZORPAYX_PAYOUT_PURPOSE") or "payout")[:30]
        default_bank_mode = (_clean_env("RAZORPAYX_PAYOUT_MODE") or "IMPS").upper()
        if default_bank_mode not in _ALLOWED_RAZORPAY_MODES:
            default_bank_mode = "IMPS"

        requested_mode = str(payment_mode or "").strip().upper()
        if requested_mode and requested_mode not in _ALLOWED_RAZORPAY_MODES:
            raise PaymentValidationError("Payment mode must be one of: UPI, IMPS, NEFT, RTGS.")

        narration_raw = re.sub(r"[^A-Za-z0-9 ]+", " ", f"Joshu {invoice_number or payee_name}").strip()
        narration = (narration_raw or "Joshu Payment")[:30]

        saved_fund_accounts = _load_json_map_env("RAZORPAYX_PAYEE_FUND_ACCOUNTS_JSON")
        saved_fund_account_id = (
            saved_fund_accounts.get(payee_email)
            or saved_fund_accounts.get(payee_name.lower())
            or (saved_fund_accounts.get(payee_upi_id) if payee_upi_id else None)
        )

        body: Dict[str, Any] = {
            "account_number": account_number,
            "amount": paise_amount,
            "currency": "INR",
            "purpose": purpose,
            "queue_if_low_balance": False,
            "reference_id": (invoice_number or payment_reference or task_id)[:40],
            "narration": narration,
            "notes": {
                "task_id": task_id,
                "approved_by": user_email,
                "invoice_number": invoice_number or "",
            },
        }

        if saved_fund_account_id:
            body["fund_account_id"] = saved_fund_account_id
            body["mode"] = requested_mode or default_bank_mode
        elif payee_upi_id:
            if not _UPI_ID_RE.match(payee_upi_id):
                raise PaymentValidationError(
                    "Invalid UPI ID format. Enter a valid UPI ID (e.g. vendor@icici or merchant@okaxis)."
                )
            body["mode"] = "UPI"
            body["fund_account"] = {
                "account_type": "vpa",
                "vpa": {"address": payee_upi_id},
                "contact": {
                    "name": payee_name[:50],
                    "email": payee_email or user_email,
                    "type": "vendor",
                    "reference_id": task_id[:40],
                },
            }
        elif payee_bank_account and payee_ifsc:
            if not _BANK_ACCT_RE.match(payee_bank_account):
                raise PaymentValidationError("Bank account number must contain 6 to 20 digits.")
            if not _IFSC_RE.match(payee_ifsc):
                raise PaymentValidationError(
                    "Invalid Indian IFSC code (expected 11 characters, e.g. HDFC0001234)."
                )
            chosen_mode = requested_mode if requested_mode in ("IMPS", "NEFT", "RTGS") else default_bank_mode
            if chosen_mode == "UPI":
                chosen_mode = "IMPS"
            body["mode"] = chosen_mode
            body["fund_account"] = {
                "account_type": "bank_account",
                "bank_account": {
                    "name": payee_name[:100],
                    "ifsc": payee_ifsc,
                    "account_number": payee_bank_account,
                },
                "contact": {
                    "name": payee_name[:50],
                    "email": payee_email or user_email,
                    "type": "vendor",
                    "reference_id": task_id[:40],
                },
            }
        else:
            raise PaymentValidationError(
                "Enter a payee UPI ID (e.g. vendor@upi) or Bank Account + IFSC in the approval form "
                "(or map the vendor in RAZORPAYX_PAYEE_FUND_ACCOUNTS_JSON) to execute a RazorpayX payout."
            )

        headers = {
            "Content-Type": "application/json",
            "X-Payout-Idempotency": idempotency_key,
        }

        try:
            resp = requests.post(
                f"{RAZORPAY_API_BASE}/payouts",
                auth=(key_id, key_secret),
                headers=headers,
                json=body,
                timeout=25,
            )
        except requests.RequestException as exc:
            raise PaymentExecutionError("Network error while contacting RazorpayX API.") from exc

        data = resp.json() if resp.content else {}
        if resp.status_code >= 400:
            err_obj = data.get("error") if isinstance(data.get("error"), dict) else {}
            err_msg = err_obj.get("description") or err_obj.get("reason") or f"RazorpayX error (HTTP {resp.status_code})"
            raise PaymentExecutionError(f"RazorpayX payout failed: {err_msg}")

        logger.info(
            "Executed RazorpayX payout task_id=%s payout_id=%s mode=%s status=%s",
            task_id,
            data.get("id"),
            body["mode"],
            data.get("status"),
        )
        return {
            "executed": True,
            "provider": f"razorpayx_{body['mode'].lower()}",
            "payment_id": data.get("id") or idempotency_key,
            "utr": data.get("utr"),
            "status": str(data.get("status") or "processing"),
            "mode": body["mode"],
            "amount": round(amount, 2),
            "currency": "INR",
            "payee_name": payee_name,
            "payee_email": payee_email,
            "invoice_number": invoice_number,
            "executed_at": datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
        }

    def _execute_stripe_payment(
        self,
        *,
        stripe_key: str,
        task_id: str,
        idempotency_key: str,
        user_email: str,
        amount: float,
        currency: str,
        payee_name: str,
        payee_email: str,
        invoice_number: str,
        payment_reference: str,
    ) -> Dict[str, Any]:
        minor_amount = _to_minor_units(amount, currency)
        headers = {
            "Authorization": f"Bearer {stripe_key}",
            "Idempotency-Key": idempotency_key,
        }

        payee_accounts = _load_json_map_env("STRIPE_PAYEE_ACCOUNTS_JSON")
        destination_acct = payee_accounts.get(payee_email) or payee_accounts.get(payee_name.lower())

        if destination_acct:
            form_data = {
                "amount": str(minor_amount),
                "currency": currency.lower(),
                "destination": destination_acct,
                "description": f"Joshu approved payment to {payee_name} {invoice_number}".strip(),
                "metadata[task_id]": task_id,
                "metadata[approved_by]": user_email,
                "metadata[invoice_number]": invoice_number or "",
            }
            try:
                resp = requests.post(
                    f"{STRIPE_API_BASE}/transfers",
                    headers=headers,
                    data=form_data,
                    timeout=20,
                )
            except requests.RequestException as exc:
                raise PaymentExecutionError("Network error while contacting Stripe API.") from exc

            data = resp.json() if resp.content else {}
            if resp.status_code >= 400:
                err_msg = (data.get("error") or {}).get("message") or f"Stripe error (HTTP {resp.status_code})"
                raise PaymentExecutionError(f"Stripe transfer failed: {err_msg}")

            logger.info("Executed Stripe transfer task_id=%s transfer_id=%s", task_id, data.get("id"))
            return {
                "executed": True,
                "provider": "stripe_transfer",
                "payment_id": data.get("id"),
                "status": "succeeded",
                "amount": round(amount, 2),
                "currency": currency,
                "payee_name": payee_name,
                "payee_email": payee_email,
                "invoice_number": invoice_number,
                "executed_at": datetime.now(timezone.utc)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z"),
            }

        customer_id = _clean_env("STRIPE_CUSTOMER_ID")
        payment_method_id = _clean_env("STRIPE_DEFAULT_PAYMENT_METHOD_ID")
        if not customer_id or not payment_method_id:
            raise PaymentGatewayNotConfiguredError(
                "STRIPE_SECRET_KEY is set, but automatic off-session execution also requires "
                "STRIPE_CUSTOMER_ID and STRIPE_DEFAULT_PAYMENT_METHOD_ID (or STRIPE_PAYEE_ACCOUNTS_JSON) in backend/.env."
            )

        form_data = {
            "amount": str(minor_amount),
            "currency": currency.lower(),
            "customer": customer_id,
            "payment_method": payment_method_id,
            "confirm": "true",
            "off_session": "true",
            "description": f"Joshu approved payment to {payee_name} {invoice_number or payment_reference}".strip(),
            "metadata[task_id]": task_id,
            "metadata[approved_by]": user_email,
            "metadata[payee_name]": payee_name,
            "metadata[payee_email]": payee_email,
            "metadata[invoice_number]": invoice_number or "",
        }
        try:
            resp = requests.post(
                f"{STRIPE_API_BASE}/payment_intents",
                headers=headers,
                data=form_data,
                timeout=20,
            )
        except requests.RequestException as exc:
            raise PaymentExecutionError("Network error while contacting Stripe API.") from exc

        data = resp.json() if resp.content else {}
        if resp.status_code >= 400:
            err_msg = (data.get("error") or {}).get("message") or f"Stripe error (HTTP {resp.status_code})"
            raise PaymentExecutionError(f"Stripe payment failed: {err_msg}")

        logger.info("Executed Stripe PaymentIntent task_id=%s pi_id=%s status=%s", task_id, data.get("id"), data.get("status"))
        return {
            "executed": True,
            "provider": "stripe",
            "payment_id": data.get("id"),
            "status": data.get("status") or "succeeded",
            "amount": round(amount, 2),
            "currency": currency,
            "payee_name": payee_name,
            "payee_email": payee_email,
            "invoice_number": invoice_number,
            "executed_at": datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
        }

    def _execute_custom_gateway_payment(
        self,
        *,
        gateway_url: str,
        api_key: str,
        task_id: str,
        idempotency_key: str,
        user_email: str,
        amount: float,
        currency: str,
        payee_name: str,
        payee_email: str,
        payee_upi_id: str,
        payee_bank_account: str,
        payee_ifsc: str,
        invoice_number: str,
        payment_reference: str,
    ) -> Dict[str, Any]:
        safe_url = _validate_public_https_url(gateway_url)
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Idempotency-Key": idempotency_key,
        }
        body = {
            "task_id": task_id,
            "approved_by": user_email,
            "amount": round(amount, 2),
            "currency": currency,
            "payee_name": payee_name,
            "payee_email": payee_email,
            "payee_upi_id": payee_upi_id or None,
            "payee_bank_account": payee_bank_account or None,
            "payee_ifsc": payee_ifsc or None,
            "invoice_number": invoice_number,
            "payment_reference": payment_reference,
        }
        try:
            resp = requests.post(safe_url, headers=headers, json=body, timeout=20)
        except requests.RequestException as exc:
            raise PaymentExecutionError("Network error while contacting configured payment gateway.") from exc

        if resp.status_code >= 400:
            raise PaymentExecutionError(f"Payment gateway rejected the payment (HTTP {resp.status_code}).")

        data = resp.json() if resp.content else {}
        return {
            "executed": True,
            "provider": "payment_gateway",
            "payment_id": str(data.get("payment_id") or data.get("id") or idempotency_key),
            "status": str(data.get("status") or "submitted"),
            "amount": round(amount, 2),
            "currency": currency,
            "payee_name": payee_name,
            "payee_email": payee_email,
            "invoice_number": invoice_number,
            "executed_at": datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
        }


payment_executor_service = PaymentExecutorService()
