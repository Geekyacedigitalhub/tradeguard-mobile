"""Fail-closed conversion of a monetary amount across cTrader asset paths.

This module converts an amount from a source asset into a target asset using
only broker-provided conversion symbols and fresh bid/ask quotes. It does not
claim to size trades by itself; callers must separately verify instrument
contract semantics, stop distance, and broker volume constraints.
"""
from __future__ import annotations

import math
from collections import deque
from collections.abc import Mapping, Sequence
from typing import Any


def _positive_finite(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise ValueError(f"{field} must be positive and finite")
    return result


def convert_asset_amount(
    amount: float,
    source_asset_id: int,
    target_asset_id: int,
    *,
    conversion_symbols: Sequence[Mapping[str, Any]],
    quotes_by_symbol_id: Mapping[int, Mapping[str, Any]],
    now_timestamp_ms: int,
    max_quote_age_ms: int = 5000,
) -> dict[str, Any]:
    """Convert amount using the broker-returned asset path and current quotes.

    For base->quote conversion, multiply by bid. For quote->base, divide by
    ask. Missing, stale, malformed, or disconnected quote paths fail closed.
    The returned rate is the effective target-asset amount per source-asset
    unit and is not a complete order-risk approval.
    """
    amount_value = _positive_finite(amount, "amount")
    for name, value in (("source_asset_id", source_asset_id), ("target_asset_id", target_asset_id),
                        ("now_timestamp_ms", now_timestamp_ms), ("max_quote_age_ms", max_quote_age_ms)):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} must be a positive integer")
    if source_asset_id == target_asset_id:
        return {"amount": amount_value, "rate": 1.0, "source_asset_id": source_asset_id,
                "target_asset_id": target_asset_id, "path": [], "quote_timestamps_ms": [],
                "conversion_verified": True, "risk_sizing_verified": False}
    if not isinstance(conversion_symbols, Sequence) or isinstance(conversion_symbols, (str, bytes)):
        raise ValueError("conversion_symbols must be a sequence")
    if not isinstance(quotes_by_symbol_id, Mapping):
        raise ValueError("quotes_by_symbol_id must be a mapping")

    # Each graph edge stores the asset direction and the quote side required
    # to convert without assuming a mid-price that may not be executable.
    graph: dict[int, list[tuple[int, int, str]]] = {}
    for symbol in conversion_symbols:
        if not isinstance(symbol, Mapping):
            raise ValueError("conversion symbol metadata is malformed")
        sid = symbol.get("symbol_id")
        base = symbol.get("base_asset_id")
        quote = symbol.get("quote_asset_id")
        if any(isinstance(v, bool) or not isinstance(v, int) or v <= 0 for v in (sid, base, quote)) or base == quote:
            raise ValueError("conversion symbol asset identifiers are invalid")
        graph.setdefault(base, []).append((quote, sid, "bid"))
        graph.setdefault(quote, []).append((base, sid, "ask"))

    queue = deque([(source_asset_id, 1.0, [], [])])
    visited = {source_asset_id}
    while queue:
        asset, rate, path, timestamps = queue.popleft()
        for next_asset, symbol_id, side in graph.get(asset, []):
            if next_asset in visited:
                continue
            quote = quotes_by_symbol_id.get(symbol_id)
            if not isinstance(quote, Mapping):
                raise ValueError(f"missing current quote for conversion symbol {symbol_id}")
            bid = _positive_finite(quote.get("bid"), f"symbol {symbol_id} bid")
            ask = _positive_finite(quote.get("ask"), f"symbol {symbol_id} ask")
            if ask < bid:
                raise ValueError(f"symbol {symbol_id} ask is below bid")
            timestamp = quote.get("timestamp_ms")
            if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp <= 0:
                raise ValueError(f"symbol {symbol_id} quote timestamp is missing")
            age = now_timestamp_ms - timestamp
            if age < 0 or age > max_quote_age_ms:
                raise ValueError(f"symbol {symbol_id} quote is stale or from the future")
            edge_rate = bid if side == "bid" else 1.0 / ask
            next_rate = rate * edge_rate
            if not math.isfinite(next_rate) or next_rate <= 0:
                raise ValueError("asset conversion rate is invalid")
            next_path = path + [{"symbol_id": symbol_id, "from_asset_id": asset,
                                 "to_asset_id": next_asset, "price_side": side}]
            next_timestamps = timestamps + [timestamp]
            if next_asset == target_asset_id:
                converted = amount_value * next_rate
                if not math.isfinite(converted) or converted <= 0:
                    raise ValueError("converted amount is invalid")
                return {"amount": converted, "rate": next_rate,
                        "source_asset_id": source_asset_id, "target_asset_id": target_asset_id,
                        "path": next_path, "quote_timestamps_ms": next_timestamps, "conversion_verified": True, "risk_sizing_verified": False}
            visited.add(next_asset)
            queue.append((next_asset, next_rate, next_path, next_timestamps))
    raise ValueError("broker conversion symbols do not connect the requested assets")
