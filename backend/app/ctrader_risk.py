"""Fail-closed cTrader risk sizing primitives.

The caller must supply a broker-derived, account-currency loss-per-price-unit
value for one lot. This module does not guess pip values or FX conversion rates.
"""
from __future__ import annotations

import math


def calculate_verified_volume(
    *,
    risk_amount: float,
    stop_distance: float,
    account_currency_loss_per_price_unit_per_lot: float,
    lot_size: int,
    min_volume: int,
    max_volume: int,
    step_volume: int,
) -> dict:
    """Calculate cTrader raw protocol volume only from complete trusted inputs.

    cTrader raw protocol volume uses 100 units per instrument unit. The computed
    volume is rounded DOWN to a valid broker step so the target risk is not
    exceeded by rounding. Inputs must already reflect the current instrument
    and current account-currency conversion.
    """
    values = (
        risk_amount,
        stop_distance,
        account_currency_loss_per_price_unit_per_lot,
    )
    if any(not math.isfinite(float(value)) or float(value) <= 0 for value in values):
        raise ValueError("Risk amount, stop distance, and account-currency loss factor must be finite and positive")
    if lot_size <= 0 or min_volume <= 0 or max_volume < min_volume or step_volume <= 0:
        raise ValueError("Broker lot size and min/max/step volume metadata are invalid")

    loss_per_lot = float(stop_distance) * float(account_currency_loss_per_price_unit_per_lot)
    if not math.isfinite(loss_per_lot) or loss_per_lot <= 0:
        raise ValueError("Calculated loss per lot is invalid")

    target_lots = float(risk_amount) / loss_per_lot
    raw_unrounded = target_lots * int(lot_size) * 100
    if not math.isfinite(raw_unrounded) or raw_unrounded <= 0:
        raise ValueError("Calculated broker volume is invalid")

    # A valid broker volume must be min_volume + N * step_volume.
    steps = math.floor((raw_unrounded - int(min_volume)) / int(step_volume))
    volume = int(min_volume + steps * int(step_volume))
    if raw_unrounded < int(min_volume) or volume < int(min_volume):
        raise ValueError("Target risk is below the symbol's minimum tradable volume")
    if volume > int(max_volume):
        volume = int(min_volume + math.floor((int(max_volume) - int(min_volume)) / int(step_volume)) * int(step_volume))
    if volume < int(min_volume) or volume > int(max_volume):
        raise ValueError("No valid broker volume is available within the symbol limits")

    lots = volume / (int(lot_size) * 100)
    estimated_risk = lots * loss_per_lot
    if not math.isfinite(estimated_risk) or estimated_risk <= 0 or estimated_risk > float(risk_amount) * (1 + 1e-12):
        raise ValueError("Calculated volume does not satisfy the risk cap")

    return {
        "broker_volume": volume,
        "lots": lots,
        "risk_amount": float(risk_amount),
        "estimated_loss_at_stop": estimated_risk,
        "loss_per_lot_at_stop": loss_per_lot,
        "broker_volume_verified": True,
        "sizing_method": "broker_metadata_and_account_currency_loss_factor",
    }
