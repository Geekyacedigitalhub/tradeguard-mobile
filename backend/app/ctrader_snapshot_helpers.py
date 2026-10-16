"""Pure helpers for normalizing cTrader snapshot values."""

from __future__ import annotations

import re


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


def _integer_minor_units(raw_value: object) -> int | None:
    """Parse exact integer protocol units without accepting lossy float conversion."""
    if isinstance(raw_value, bool) or raw_value is None:
        return None
    if isinstance(raw_value, int):
        value = raw_value
    elif isinstance(raw_value, str):
        text = raw_value.strip()
        if not re.fullmatch(r"-?(0|[1-9][0-9]*)", text):
            return None
        try:
            value = int(text)
        except (ValueError, OverflowError):
            return None
    else:
        # Broker monetary protocol fields are integer minor units; floats and
        # Decimal values are not accepted because precision may already be lost.
        return None
    if abs(value) > 2**53:
        return None
    return value


def scale_balance(raw_balance: object, money_digits: object) -> float | None:
    """Scale exact integer broker money units; reject lossy or malformed values."""
    if raw_balance is None or money_digits is None or isinstance(money_digits, bool):
        return None
    try:
        digits = int(money_digits)
        if isinstance(money_digits, float) and not money_digits.is_integer():
            return None
        if isinstance(money_digits, str) and str(digits) != money_digits.strip():
            return None
    except (TypeError, ValueError, OverflowError):
        return None
    if digits < 0 or digits > 12:
        return None
    balance = _integer_minor_units(raw_balance)
    if balance is None:
        return None
    return balance / (10 ** digits)


def positive_integer(raw_value: object) -> int | None:
    """Return a positive integer identifier/volume, rejecting malformed broker values."""
    if raw_value is None or isinstance(raw_value, bool):
        return None
    try:
        value = int(raw_value)
        if isinstance(raw_value, float) and not raw_value.is_integer():
            return None
        if isinstance(raw_value, str) and str(value) != raw_value.strip():
            return None
    except (TypeError, ValueError, OverflowError):
        return None
    return value if value > 0 else None


def scale_unrealized_pnl(rows: object, money_digits: object) -> float | None:
    """Scale a complete broker P/L response; reject partial or malformed values."""
    if rows is None or money_digits is None:
        return None
    if isinstance(rows, (str, bytes, dict)):
        return None
    try:
        values = list(rows)
    except (TypeError, ValueError):
        return None
    total = 0
    for row in values:
        raw_value = getattr(row, "netUnrealizedPnL", None)
        value = _integer_minor_units(raw_value)
        if value is None:
            return None
        total += value
        if abs(total) > 2**53:
            return None
    return scale_balance(total, money_digits)


def normalize_currency_code(raw_currency: object) -> str | None:
    """Accept only normalized three-letter ASCII currency codes from broker metadata."""
    if not isinstance(raw_currency, str):
        return None
    value = raw_currency.strip().upper()
    return value if re.fullmatch(r"[A-Z]{3}", value) else None
