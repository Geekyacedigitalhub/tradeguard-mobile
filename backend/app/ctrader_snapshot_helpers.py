"""Pure helpers for normalizing cTrader snapshot values."""

from __future__ import annotations


def normalize_trade_side(raw_side: object) -> str:
    """Map cTrader trade-side enum values to explicit display-safe labels."""
    if raw_side is None or isinstance(raw_side, bool):
        return "UNKNOWN"
    try:
        value = int(raw_side)
        if isinstance(raw_side, float) and not raw_side.is_integer():
            return "UNKNOWN"
        if isinstance(raw_side, str) and str(value) != raw_side.strip():
            return "UNKNOWN"
    except (TypeError, ValueError, OverflowError):
        return "UNKNOWN"
    if value == 1:
        return "BUY"
    if value == 2:
        return "SELL"
    return "UNKNOWN"


def scale_balance(raw_balance: object, money_digits: object) -> float | None:
    """Scale broker money units only when both source fields are present and valid."""
    if raw_balance is None or money_digits is None:
        return None
    # bool is a numeric subtype in Python, but it is never a valid broker balance.
    if isinstance(raw_balance, bool) or isinstance(money_digits, bool):
        return None
    try:
        digits = int(money_digits)
        if isinstance(money_digits, float) and not money_digits.is_integer():
            return None
        if isinstance(money_digits, str) and str(digits) != money_digits.strip():
            return None
        balance = float(raw_balance)
    except (TypeError, ValueError, OverflowError):
        return None
    if digits < 0 or digits > 12:
        return None
    if not (float("-inf") < balance < float("inf")):
        return None
    return balance / (10 ** digits)
