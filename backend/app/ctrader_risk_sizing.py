"""Fail-closed stop-loss risk estimation and broker-volume sizing.

The supported loss model is for linear FX-style instruments where one base
currency unit loses |entry - stop| units of the quote currency. Do not use this
model for indices, metals, futures, crypto CFDs, or instruments with different
contract/tick-value semantics unless a broker-specific calculator is added.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from .ctrader_conversion import convert_asset_amount
from .ctrader_volume_validation import validate_symbol_volume_metadata


PROTOCOL_VOLUME_UNITS_PER_BASE_UNIT = 100


def _positive_finite(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise ValueError(f"{field} must be positive and finite")
    return result


def estimate_fx_stop_loss(
    *,
    volume_raw: int,
    entry_price: float,
    stop_price: float,
    base_asset_id: int,
    quote_asset_id: int,
    account_asset_id: int,
    conversion_symbols: Sequence[Mapping[str, Any]],
    quotes_by_symbol_id: Mapping[int, Mapping[str, Any]],
    now_timestamp_ms: int,
    max_quote_age_ms: int = 5000,
) -> dict[str, Any]:
    """Estimate planned FX stop loss in deposit currency using executable-side conversion."""
    if isinstance(volume_raw, bool) or not isinstance(volume_raw, int) or volume_raw <= 0:
        raise ValueError("volume_raw must be a positive broker protocol integer")
    for name, value in (("base_asset_id", base_asset_id), ("quote_asset_id", quote_asset_id),
                        ("account_asset_id", account_asset_id)):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} must be a positive integer")
    entry = _positive_finite(entry_price, "entry_price")
    stop = _positive_finite(stop_price, "stop_price")
    if entry == stop:
        raise ValueError("stop price must differ from entry price")
    if base_asset_id == quote_asset_id:
        raise ValueError("base and quote assets must differ")

    # Raw cTrader volume is in hundredths of a unit for this supported model.
    base_units = volume_raw / PROTOCOL_VOLUME_UNITS_PER_BASE_UNIT
    quote_loss = abs(entry - stop) * base_units
    if not math.isfinite(quote_loss) or quote_loss <= 0:
        raise ValueError("calculated quote-currency loss is invalid")

    if quote_asset_id == account_asset_id:
        converted = {
            "amount": quote_loss, "rate": 1.0,
            "source_asset_id": quote_asset_id, "target_asset_id": account_asset_id,
            "path": [], "quote_timestamps_ms": [], "conversion_verified": True,
            "risk_sizing_verified": False,
        }
    else:
        converted = convert_asset_amount(
            quote_loss, quote_asset_id, account_asset_id,
            conversion_symbols=conversion_symbols,
            quotes_by_symbol_id=quotes_by_symbol_id,
            now_timestamp_ms=now_timestamp_ms,
            max_quote_age_ms=max_quote_age_ms,
        )
    return {
        "volume_raw": volume_raw,
        "base_units": base_units,
        "entry_price": entry,
        "stop_price": stop,
        "stop_distance": abs(entry - stop),
        "quote_asset_id": quote_asset_id,
        "account_asset_id": account_asset_id,
        "estimated_loss_quote_currency": quote_loss,
        "estimated_loss_account_currency": converted["amount"],
        "conversion_path": converted["path"],
        "quote_timestamps_ms": converted["quote_timestamps_ms"],
        "conversion_verified": converted["conversion_verified"],
        "risk_sizing_verified": False,
        "model": "linear_fx_base_units",
    }


def size_fx_volume_for_risk(
    *,
    risk_budget_account_currency: float,
    entry_price: float,
    stop_price: float,
    base_asset_id: int,
    quote_asset_id: int,
    account_asset_id: int,
    conversion_symbols: Sequence[Mapping[str, Any]],
    quotes_by_symbol_id: Mapping[int, Mapping[str, Any]],
    now_timestamp_ms: int,
    min_volume: int,
    max_volume: int,
    step_volume: int,
    max_quote_age_ms: int = 5000,
) -> dict[str, Any]:
    """Choose the largest broker-step FX volume not exceeding the risk budget."""
    budget = _positive_finite(risk_budget_account_currency, "risk budget")
    minimum, maximum, step = validate_symbol_volume_metadata(min_volume, max_volume, step_volume)

    # Determine loss for one raw protocol volume unit; scaling is linear for FX.
    unit = estimate_fx_stop_loss(
        volume_raw=100,
        entry_price=entry_price, stop_price=stop_price,
        base_asset_id=base_asset_id, quote_asset_id=quote_asset_id,
        account_asset_id=account_asset_id,
        conversion_symbols=conversion_symbols, quotes_by_symbol_id=quotes_by_symbol_id,
        now_timestamp_ms=now_timestamp_ms, max_quote_age_ms=max_quote_age_ms,
    )
    loss_per_raw_unit = unit["estimated_loss_account_currency"] / 100
    if not math.isfinite(loss_per_raw_unit) or loss_per_raw_unit <= 0:
        raise ValueError("loss per protocol volume unit is invalid")

    # Round down from the budget to the broker step. Broker minimum is not
    # forced when it would breach risk; such a trade is rejected instead.
    raw_budget_volume = math.floor((budget / loss_per_raw_unit) + 1e-12)
    aligned = (raw_budget_volume // step) * step
    if aligned < minimum:
        raise ValueError("risk budget is too small for the broker minimum volume")
    volume = min(aligned, maximum)
    volume = (volume // step) * step
    if volume < minimum:
        raise ValueError("no valid broker volume fits within the risk budget")

    estimate = estimate_fx_stop_loss(
        volume_raw=volume,
        entry_price=entry_price, stop_price=stop_price,
        base_asset_id=base_asset_id, quote_asset_id=quote_asset_id,
        account_asset_id=account_asset_id,
        conversion_symbols=conversion_symbols, quotes_by_symbol_id=quotes_by_symbol_id,
        now_timestamp_ms=now_timestamp_ms, max_quote_age_ms=max_quote_age_ms,
    )
    if estimate["estimated_loss_account_currency"] > budget + max(1e-9, budget * 1e-12):
        raise ValueError("rounded broker volume exceeds the configured risk budget")
    return {
        **estimate,
        "risk_budget_account_currency": budget,
        "risk_utilization": estimate["estimated_loss_account_currency"] / budget,
        "min_volume": minimum,
        "max_volume": maximum,
        "step_volume": step,
        "risk_sizing_verified": False,
        "requires_broker_specific_contract_verification": True,
    }
