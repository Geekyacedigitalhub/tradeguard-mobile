"""Read-only cTrader symbol catalogue normalization.

Broker symbol names and asset IDs are metadata only; this module never infers
instrument class or authorizes automated risk sizing.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def normalize_symbol_catalog(symbols: Iterable[Any], *, query: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 250:
        raise ValueError("limit must be an integer between 1 and 250")
    needle = query.strip().casefold() if isinstance(query, str) else ""
    rows = []
    seen = set()
    for symbol in symbols:
        symbol_id = _positive_int(getattr(symbol, "symbolId", None))
        name = getattr(symbol, "symbolName", None)
        digits = getattr(symbol, "digits", None)
        lot_size = getattr(symbol, "lotSize", None)
        min_volume = _positive_int(getattr(symbol, "minVolume", None))
        max_volume = _positive_int(getattr(symbol, "maxVolume", None))
        step_volume = _positive_int(getattr(symbol, "stepVolume", None))
        base_asset_id = _positive_int(getattr(symbol, "baseAssetId", None))
        quote_asset_id = _positive_int(getattr(symbol, "quoteAssetId", None))
        if symbol_id is None or not isinstance(name, str) or not name.strip() or symbol_id in seen:
            continue
        if isinstance(digits, bool) or not isinstance(digits, int) or not 0 <= digits <= 12:
            digits = None
        if isinstance(lot_size, bool) or not isinstance(lot_size, int) or lot_size <= 0:
            lot_size = None
        volume_valid = (
            min_volume is not None and max_volume is not None and step_volume is not None
            and max_volume >= min_volume and (max_volume - min_volume) % step_volume == 0
        )
        if needle and needle not in name.casefold():
            continue
        seen.add(symbol_id)
        rows.append({
            "symbol_id": symbol_id,
            "symbol_name": name.strip(),
            "digits": digits,
            "lot_size": lot_size,
            "base_asset_id": base_asset_id,
            "quote_asset_id": quote_asset_id,
            "min_volume": min_volume,
            "max_volume": max_volume,
            "step_volume": step_volume,
            "volume_constraints_valid": bool(volume_valid),
            "instrument_type": None,
            "contract_model": None,
            "risk_sizing_verified": False,
        })
        if len(rows) >= limit:
            break
    return rows
