"""Pure helpers for normalizing cTrader snapshot values."""

from __future__ import annotations


def normalize_trade_side(raw_side: object) -> str:
    """Map cTrader trade-side enum values to explicit display-safe labels."""
    try:
        value = int(raw_side) if raw_side is not None else 0
    except (TypeError, ValueError):
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
    try:
        digits = int(money_digits)
        balance = float(raw_balance)
    except (TypeError, ValueError, OverflowError):
        return None
    if digits < 0 or digits > 12:
        return None
    if not (float("-inf") < balance < float("inf")):
        return None
    return balance / (10 ** digits)
