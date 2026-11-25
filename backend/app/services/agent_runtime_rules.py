"""Auto-managed runtime rules module updated by Joshu Agent when autonomous policies change."""

from __future__ import annotations

AUTO_PAY_ENABLED: bool = False
AUTO_PAY_MAX_AMOUNT: float = 0.0
AUTO_PAY_CURRENCY: str = "INR"
AUTO_ARCHIVE_INFORMATIONAL: bool = False
AUTO_ADD_CALENDAR_INVITES: bool = False
AUTO_SEND_REPLIES: bool = False


def should_auto_execute_payment(amount: float | int | None, currency: str = "INR") -> bool:
    """Return True if a payment of `amount` should be executed automatically without asking the user."""
    if not AUTO_PAY_ENABLED or amount is None:
        return False
    try:
        numeric_amount = float(amount)
    except (TypeError, ValueError):
        return False
    return 0.0 < numeric_amount <= AUTO_PAY_MAX_AMOUNT
