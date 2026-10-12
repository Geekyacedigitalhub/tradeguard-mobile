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
    if isinstance(position_id, bool) or not isinstance(position_id, int) or position_id <= 0:
        raise ValueError("cTrader protection requires a positive integer position id")
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

def validate_positive_identifier(value: Any, field: str) -> int:
    """Require a positive integer protocol identifier without coercion."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"cTrader {field} must be a positive integer")
    return value
