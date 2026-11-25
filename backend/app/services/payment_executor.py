"""Real automatic payment execution service (Stripe API or allowlisted HTTPS payment gateway)."""

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

DEFAULT_MAX_AUTO_AMOUNT = 5000.0
STRIPE_API_BASE = "https://api.stripe.com/v1"
_ISO_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_ZERO_DECIMAL_CURRENCIES = {
    "BIF", "CLP", "DJF", "GNF", "JPY", "KMF", "KRW", "MGA",
    "PYG", "RWF", "UGX", "VND", "VUV", "XAF", "XOF", "XPF",
}


class PaymentExecutionError(RuntimeError):
    """Base error raised when executing an automatic payment fails."""


class PaymentGatewayNotConfiguredError(PaymentExecutionError):
    """Raised when no real payment gateway credentials are configured in backend/.env."""


class PaymentValidationError(PaymentExecutionError):
    """Raised when payment amount, currency, or ceiling validation fails."""


def _clean_env(name: str) -> str:
    val = (os.getenv(name) or "").strip()
    if not val:
        return ""
    upper = val.upper()
    if any(upper.startswith(p) for p in ("YOUR_", "REPLACE_", "<")):
        return ""
    return val


def is_payment_gateway_configured() -> bool:
    """Return True if Stripe or a custom HTTPS payment gateway API is configured."""
    has_stripe = bool(_clean_env("STRIPE_SECRET_KEY"))
    has_custom = bool(_clean_env("PAYMENT_API_URL") and _clean_env("PAYMENT_API_KEY"))
    return has_stripe or has_custom


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


def _load_stripe_payee_accounts() -> Dict[str, str]:
    raw = _clean_env("STRIPE_PAYEE_ACCOUNTS_JSON")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return {str(k).strip().lower(): str(v).strip() for k, v in parsed.items() if k and v}
    except Exception:
        logger.warning("Invalid STRIPE_PAYEE_ACCOUNTS_JSON; ignoring payee mapping")
    return {}


class PaymentExecutorService:
    """Executes real automatic payments via Stripe or a configured HTTPS Payment Gateway API."""

    def execute_payment(
        self,
        *,
        task_id: str,
        user_email: str,
        amount: float,
        currency: str,
        payee_name: str,
        payee_email: str = "",
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

        norm_currency = str(currency or "USD").strip().upper()
        if not _ISO_CURRENCY_RE.match(norm_currency):
            raise PaymentValidationError("Currency must be a valid 3-letter ISO code (e.g. USD, INR, EUR).")

        clean_payee = str(payee_name or payee_email or "Vendor").strip()[:160]
        clean_payee_email = str(payee_email or "").strip().lower()[:160]
        idempotency_key = f"joshu-pay-{task_id}"

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
                invoice_number=invoice_number,
                payment_reference=payment_reference,
            )

        raise PaymentGatewayNotConfiguredError(
            "Automatic payment gateway is not configured in backend/.env. "
            "Configure STRIPE_SECRET_KEY (with STRIPE_CUSTOMER_ID and STRIPE_DEFAULT_PAYMENT_METHOD_ID, "
            "or STRIPE_PAYEE_ACCOUNTS_JSON) or PAYMENT_API_URL + PAYMENT_API_KEY, then restart the backend."
        )

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

        payee_accounts = _load_stripe_payee_accounts()
        destination_acct = payee_accounts.get(payee_email) or payee_accounts.get(payee_name.lower())

        # Mode A: Stripe Connect Transfer to a verified payee Connected Account
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

        # Mode B: Stripe off-session PaymentIntent using configured server-side customer & payment method
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
