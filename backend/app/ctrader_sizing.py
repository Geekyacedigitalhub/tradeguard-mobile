"""Risk-based cTrader order sizing primitives.

This module deliberately does not guess a symbol's monetary value or convert
quote currency into deposit currency. Callers must supply a verified
account-currency loss value for one traded unit per one full price unit.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

PROTOCOL_VOLUME_PER_UNIT = 100


def calculate_protocol_volume(
    *,
    risk_amount: float,
    stop_distance: float,
    account_currency_loss_per_price_unit_per_traded_unit: float,
    constraints: Mapping[str, Any],
) -> dict[str, float | int]:
    """Calculate a step-aligned protocol volume without exceeding target risk.

    The monetary-value input must already reflect this instrument's contract
    specification and any required quote/deposit currency conversion. It is
    intentionally an explicit required input.

    Returns protocol volume (100 = one traded unit), estimated account-currency
    risk, and per-unit risk. Raises if required inputs are unavailable.
    """
    inputs = (
        risk_amount,
        stop_distance,
        account_currency_loss_per_price_unit_per_traded_unit,
    )
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 for v in inputs):
        raise ValueError("Risk amount, stop distance, and verified account-currency value must be positive finite numbers")

    try:
        minimum = int(constraints.get("min_volume") or 0)
        maximum = int(constraints.get("max_volume") or 0)
        step = int(constraints.get("step_volume") or 0)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("Broker volume constraints are invalid") from None
    if minimum <= 0 or maximum < minimum or step <= 0:
        raise ValueError("Broker volume constraints are missing or invalid")

    risk_per_traded_unit = float(stop_distance) * float(account_currency_loss_per_price_unit_per_traded_unit)
    if not math.isfinite(risk_per_traded_unit) or risk_per_traded_unit <= 0:
        raise ValueError("Calculated risk per traded unit is invalid")

    raw_protocol = math.floor((float(risk_amount) / risk_per_traded_unit) * PROTOCOL_VOLUME_PER_UNIT)
    if raw_protocol < minimum:
        raise ValueError("Target risk is too small for this symbol's minimum broker volume")

    # Align downward from the broker minimum so rounding cannot increase risk.
    aligned = minimum + ((raw_protocol - minimum) // step) * step
    if aligned > maximum:
        raise ValueError("Target risk implies a volume above the broker maximum; order rejected rather than silently capped")

    traded_units = aligned / PROTOCOL_VOLUME_PER_UNIT
    estimated_risk = traded_units * risk_per_traded_unit
    if estimated_risk > float(risk_amount) + max(1e-9, float(risk_amount) * 1e-12):
        raise ValueError("Calculated volume would exceed the requested risk")
    return {
        "protocol_volume": aligned,
        "traded_units": traded_units,
        "estimated_risk": estimated_risk,
        "risk_per_traded_unit": risk_per_traded_unit,
    }
