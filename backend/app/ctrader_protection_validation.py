"""Strict validation for cTrader position-protection requests."""
from __future__ import annotations

import math
from typing import Any


def validate_protection_request(
    position_id: Any,
    stop_loss: Any = None,
    take_profit: Any = None,
) -> tuple[int, float | None, float | None]:
    """Reject malformed identifiers/prices before building a broker request.

    Prices must be finite, positive numeric values (not booleans or strings).
    At least one of stop_loss/take_profit must be provided.
    """
    validate_positive_identifier(position_id, "protection position id")
    if stop_loss is None and take_profit is None:
        raise ValueError("cTrader protection requires a stop loss or take profit")

    def price(value: Any, field: str) -> float | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"cTrader {field} must be a positive finite number")
        parsed = float(value)
        if not math.isfinite(parsed) or parsed <= 0:
            raise ValueError(f"cTrader {field} must be a positive finite number")
        return parsed

    return (
        position_id,
        price(stop_loss, "stop loss"),
        price(take_profit, "take profit"),
    )

_MAX_PROTOCOL_ID = (1 << 63) - 1


def validate_positive_identifier(value: Any, field: str) -> int:
    """Require a positive signed-64-bit protocol identifier without coercion."""
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
        or value > _MAX_PROTOCOL_ID
    ):
        raise ValueError(f"cTrader {field} must be a valid positive protocol integer")
    return value


def validate_deal_window(from_timestamp: Any, to_timestamp: Any, max_rows: Any = 1000) -> tuple[int, int, int]:
    """Validate a bounded cTrader deal-history request without coercion."""
    start = validate_positive_identifier(from_timestamp, "deal start timestamp")
    end = validate_positive_identifier(to_timestamp, "deal end timestamp")
    limit = validate_positive_identifier(max_rows, "deal row limit")
    if end <= start:
        raise ValueError("cTrader deal end timestamp must be later than start timestamp")
    if limit > 1000:
        raise ValueError("cTrader deal row limit must not exceed 1000")
    return start, end, limit
