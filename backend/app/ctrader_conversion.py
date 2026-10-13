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
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{field} must be positive and finite") from exc
    if not math.isfinite(result) or result <= 0:
        raise ValueError(f"{field} must be positive and finite")
    return result



def normalize_conversion_symbols(symbols: Any) -> list[dict[str, Any]]:
    """Validate broker conversion-symbol metadata before graph construction.

    Protocol identifiers must already be positive integers; coercing malformed
    strings or booleans could silently bind a quote to the wrong instrument.
    """
    if not isinstance(symbols, Sequence) or isinstance(symbols, (str, bytes)):
        raise ValueError("conversion symbols must be a sequence")
    normalized: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for item in symbols:
        if not isinstance(item, Mapping):
            raise ValueError("conversion symbol metadata is malformed")
        symbol_id = item.get("symbol_id")
        name = item.get("symbol_name")
        base_id = item.get("base_asset_id")
        quote_id = item.get("quote_asset_id")
        if (
            isinstance(symbol_id, bool) or not isinstance(symbol_id, int) or symbol_id <= 0
            or isinstance(base_id, bool) or not isinstance(base_id, int) or base_id <= 0
            or isinstance(quote_id, bool) or not isinstance(quote_id, int) or quote_id <= 0
            or base_id == quote_id
            or not isinstance(name, str) or not name.strip()
        ):
            raise ValueError("conversion symbol metadata contains invalid identifiers or name")
        if symbol_id in seen_ids:
            raise ValueError("conversion symbol metadata contains duplicate symbol IDs")
        seen_ids.add(symbol_id)
        normalized.append({
            "symbol_id": symbol_id,
            "symbol_name": name.strip(),
            "base_asset_id": base_id,
            "quote_asset_id": quote_id,
        })
    if not normalized:
        raise ValueError("conversion symbol metadata is empty")
    return normalized


def quotes_from_spot_snapshot(
    conversion_symbols: Sequence[Mapping[str, Any]],
    latest_spots_by_symbol_id: Mapping[int, Mapping[str, Any]],
    *,
    now_timestamp_ms: int,
    max_quote_age_ms: int = 5000,
) -> dict[int, dict[str, Any]]:
    """Extract fresh, executable-side quote evidence for every required symbol.

    The input must be a broker-derived snapshot keyed by symbol ID. Partial,
    stale, future-dated, malformed, or crossed quotes fail closed rather than
    returning a partial mapping that could accidentally be used for sizing.
    """
    for name, value in (("now_timestamp_ms", now_timestamp_ms), ("max_quote_age_ms", max_quote_age_ms)):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} must be a positive integer")
    if not isinstance(conversion_symbols, Sequence) or isinstance(conversion_symbols, (str, bytes)):
        raise ValueError("conversion_symbols must be a sequence")
    if not isinstance(latest_spots_by_symbol_id, Mapping):
        raise ValueError("latest_spots_by_symbol_id must be a mapping")
    required_ids: set[int] = set()
    for symbol in conversion_symbols:
        if not isinstance(symbol, Mapping):
            raise ValueError("conversion symbol metadata is malformed")
        symbol_id = symbol.get("symbol_id")
        if isinstance(symbol_id, bool) or not isinstance(symbol_id, int) or symbol_id <= 0:
            raise ValueError("conversion symbol metadata contains an invalid symbol ID")
        if symbol_id in required_ids:
            raise ValueError("conversion symbols contain duplicate symbol IDs")
        required_ids.add(symbol_id)
    if not required_ids:
        return {}
    quotes: dict[int, dict[str, Any]] = {}
    for symbol_id in required_ids:
        spot = latest_spots_by_symbol_id.get(symbol_id)
        if not isinstance(spot, Mapping):
            raise ValueError(f"fresh broker spot quote is missing for conversion symbol {symbol_id}")
        bid = _positive_finite(spot.get("bid"), f"symbol {symbol_id} bid")
        ask = _positive_finite(spot.get("ask"), f"symbol {symbol_id} ask")
        if ask < bid:
            raise ValueError(f"symbol {symbol_id} ask is below bid")
        timestamp = spot.get("timestamp_ms", spot.get("timestamp"))
        if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp <= 0:
            raise ValueError(f"symbol {symbol_id} quote timestamp is invalid")
        age = now_timestamp_ms - timestamp
        if age < 0 or age > max_quote_age_ms:
            raise ValueError(f"symbol {symbol_id} quote is stale or from the future")
        quotes[symbol_id] = {"bid": bid, "ask": ask, "timestamp_ms": timestamp}
    return quotes


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
    seen_symbol_ids: set[int] = set()
    for symbol in conversion_symbols:
        if not isinstance(symbol, Mapping):
            raise ValueError("conversion symbol metadata is malformed")
        sid = symbol.get("symbol_id")
        base = symbol.get("base_asset_id")
        quote = symbol.get("quote_asset_id")
        if any(isinstance(v, bool) or not isinstance(v, int) or v <= 0 for v in (sid, base, quote)) or base == quote:
            raise ValueError("conversion symbol asset identifiers are invalid")
        if sid in seen_symbol_ids:
            raise ValueError("conversion symbols contain duplicate symbol IDs")
        seen_symbol_ids.add(sid)
        graph.setdefault(base, []).append((quote, sid, "bid"))
        graph.setdefault(quote, []).append((base, sid, "ask"))

    # Evaluate every simple quoted path (with a hard work bound) and choose
    # the highest target-currency amount. Returning the first BFS path can
    # understate stop-loss risk when multiple broker conversion routes exist.
    # A malformed quote invalidates only the edge that depends on it.
    queue = deque([(source_asset_id, 1.0, [], [], frozenset({source_asset_id}))])
    best = None
    explored = 0
    max_path_states = 10000
    while queue:
        asset, rate, path, timestamps, visited_assets = queue.popleft()
        for next_asset, symbol_id, side in graph.get(asset, []):
            if next_asset in visited_assets:
                continue
            explored += 1
            if explored > max_path_states:
                raise ValueError("conversion graph is too ambiguous to size safely")
            quote = quotes_by_symbol_id.get(symbol_id)
            try:
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
            except ValueError:
                continue
            edge_rate = bid if side == "bid" else 1.0 / ask
            next_rate = rate * edge_rate
            if not math.isfinite(next_rate) or next_rate <= 0:
                raise ValueError("asset conversion rate is invalid")
            next_path = path + [{"symbol_id": symbol_id, "from_asset_id": asset,
                                 "to_asset_id": next_asset, "price_side": side}]
            next_timestamps = timestamps + [timestamp]
            if next_asset == target_asset_id:
                candidate = (next_rate, next_path, next_timestamps)
                if best is None or candidate[0] > best[0]:
                    best = candidate
                continue
            queue.append((next_asset, next_rate, next_path, next_timestamps,
                          visited_assets | {next_asset}))
    if best is None:
        raise ValueError("no fully quoted, fresh broker conversion path connects the requested assets")
    best_rate, best_path, best_timestamps = best
    converted = amount_value * best_rate
    if not math.isfinite(converted) or converted <= 0:
        raise ValueError("converted amount is invalid")
    return {"amount": converted, "rate": best_rate,
            "source_asset_id": source_asset_id, "target_asset_id": target_asset_id,
            "path": best_path, "quote_timestamps_ms": best_timestamps,
            "conversion_verified": True, "risk_sizing_verified": False}
