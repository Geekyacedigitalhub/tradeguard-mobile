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


def calculate_fresh_conversion_rate(
    *,
    first_asset_id: int,
    last_asset_id: int,
    conversion_symbols: list[dict],
    quotes_by_symbol_id: dict[int, dict],
    now_epoch_seconds: float,
    max_quote_age_seconds: float = 15.0,
) -> float:
    """Convert one unit of the first asset into the last using fresh broker quotes.

    Each symbol must provide symbol_id, base_asset_id, and quote_asset_id.
    Each quote must provide positive bid/ask and a Unix timestamp in seconds.
    Base-to-quote conversion uses bid; quote-to-base conversion uses 1 / ask.
    Missing, stale, ambiguous, or disconnected paths fail closed.
    """
    if (
        isinstance(first_asset_id, bool)
        or isinstance(last_asset_id, bool)
        or int(first_asset_id) <= 0
        or int(last_asset_id) <= 0
    ):
        raise ValueError("Conversion asset IDs must be positive")
    if not math.isfinite(float(now_epoch_seconds)) or float(now_epoch_seconds) <= 0:
        raise ValueError("Current time must be a positive finite timestamp")
    if not math.isfinite(float(max_quote_age_seconds)) or float(max_quote_age_seconds) <= 0:
        raise ValueError("Maximum quote age must be finite and positive")
    if int(first_asset_id) == int(last_asset_id):
        return 1.0
    if not conversion_symbols:
        raise ValueError("cTrader returned no conversion symbols")

    # Validate and index all edges before traversing so malformed broker data
    # cannot be silently skipped in favor of a different route.
    edges = []
    seen_ids = set()
    for symbol in conversion_symbols:
        try:
            symbol_id = int(symbol["symbol_id"])
            base_id = int(symbol["base_asset_id"])
            quote_id = int(symbol["quote_asset_id"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("Conversion symbol metadata is incomplete")
        if symbol_id <= 0 or base_id <= 0 or quote_id <= 0 or base_id == quote_id:
            raise ValueError("Conversion symbol asset metadata is invalid")
        if symbol_id in seen_ids:
            raise ValueError("Conversion chain contains duplicate symbols")
        seen_ids.add(symbol_id)
        quote = quotes_by_symbol_id.get(symbol_id)
        if not quote:
            raise ValueError("A conversion symbol has no quote")
        try:
            bid = float(quote["bid"])
            ask = float(quote["ask"])
            timestamp = float(quote["timestamp"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("A conversion quote is incomplete")
        if not all(math.isfinite(v) and v > 0 for v in (bid, ask, timestamp)):
            raise ValueError("A conversion quote contains invalid values")
        age = float(now_epoch_seconds) - timestamp
        if age < -5 or age > float(max_quote_age_seconds):
            raise ValueError("A conversion quote is stale or from the future")
        if ask < bid:
            raise ValueError("A conversion quote has crossed bid/ask prices")
        edges.append((symbol_id, base_id, quote_id, bid, ask))

    current_asset = int(first_asset_id)
    rate = 1.0
    unused = list(edges)
    while current_asset != int(last_asset_id):
        candidates = [edge for edge in unused if current_asset in (edge[1], edge[2])]
        if len(candidates) != 1:
            raise ValueError("Conversion chain is disconnected or ambiguous")
        edge = candidates[0]
        unused.remove(edge)
        _, base_id, quote_id, bid, ask = edge
        if current_asset == base_id:
            rate *= bid
            current_asset = quote_id
        else:
            rate /= ask
            current_asset = base_id
        if not math.isfinite(rate) or rate <= 0:
            raise ValueError("Calculated conversion rate is invalid")
        if len(unused) > len(edges):
            raise ValueError("Conversion chain traversal failed")

    if not math.isfinite(rate) or rate <= 0:
        raise ValueError("Calculated conversion rate is invalid")
    return rate
