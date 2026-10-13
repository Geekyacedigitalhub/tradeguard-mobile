"""Read-only pre-trade readiness checks for cTrader.

This layer reports what is missing; it does not approve sizing or submit orders.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any


def evaluate_pretrade_readiness(
    *,
    account_id: int,
    environment: str,
    deposit_asset_id: int | None,
    symbol: Mapping[str, Any],
    trade_side: str,
    entry_price: float,
    stop_price: float,
) -> dict[str, Any]:
    blockers: list[str] = []
    if isinstance(account_id, bool) or not isinstance(account_id, int) or account_id <= 0:
        blockers.append("Selected account identity is invalid.")
    normalized_environment = str(environment or "").strip().lower()
    if normalized_environment not in ("demo", "live"):
        blockers.append("Selected account environment is unknown.")
    if normalized_environment == "live":
        blockers.append("Automated entries on Live accounts are disabled.")
    if isinstance(deposit_asset_id, bool) or not isinstance(deposit_asset_id, int) or deposit_asset_id <= 0:
        blockers.append("Broker deposit-currency asset ID is unavailable.")
    if not isinstance(symbol, Mapping):
        symbol = {}
        blockers.append("Broker symbol metadata is unavailable.")
    symbol_id = symbol.get("symbol_id")
    if isinstance(symbol_id, bool) or not isinstance(symbol_id, int) or symbol_id <= 0:
        blockers.append("Broker symbol ID is invalid.")
    base_id = symbol.get("base_asset_id")
    quote_id = symbol.get("quote_asset_id")
    for field, value in (("base", base_id), ("quote", quote_id)):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            blockers.append(f"Broker {field}-asset ID is unavailable.")
    if isinstance(base_id, int) and not isinstance(base_id, bool) and isinstance(quote_id, int) and not isinstance(quote_id, bool) and base_id == quote_id:
        blockers.append("Broker base and quote assets are identical.")
    if symbol.get("volume_constraints_valid") is not True:
        blockers.append("Broker minimum, maximum, and step-volume constraints are not valid.")
    if symbol.get("instrument_type") != "FX" or symbol.get("contract_model") != "linear_fx_base_units":
        blockers.append("Broker has not verified this symbol as a supported linear FX contract.")
    side = trade_side.upper() if isinstance(trade_side, str) else ""
    if side not in ("BUY", "SELL"):
        blockers.append("Trade side must be BUY or SELL.")
    valid_prices = (
        not isinstance(entry_price, bool) and isinstance(entry_price, (int, float))
        and not isinstance(stop_price, bool) and isinstance(stop_price, (int, float))
        and math.isfinite(float(entry_price)) and math.isfinite(float(stop_price))
        and float(entry_price) > 0 and float(stop_price) > 0
    )
    if not valid_prices:
        blockers.append("Entry and stop-loss prices must be positive finite numbers.")
    elif side == "BUY" and float(stop_price) >= float(entry_price):
        blockers.append("BUY stop-loss must be below entry price.")
    elif side == "SELL" and float(stop_price) <= float(entry_price):
        blockers.append("SELL stop-loss must be above entry price.")
    if isinstance(quote_id, int) and not isinstance(quote_id, bool) and isinstance(deposit_asset_id, int) and not isinstance(deposit_asset_id, bool):
        if quote_id != deposit_asset_id:
            blockers.append("Account-currency conversion quotes have not been verified for this preflight.")
    return {
        "ready": not blockers,
        "status": "ready" if not blockers else "blocked",
        "blockers": blockers,
        "account_id": account_id if isinstance(account_id, int) and not isinstance(account_id, bool) else None,
        "environment": normalized_environment or None,
        "symbol_id": symbol_id if isinstance(symbol_id, int) and not isinstance(symbol_id, bool) else None,
        "symbol_name": symbol.get("symbol_name") if isinstance(symbol.get("symbol_name"), str) else None,
        "trade_side": side or None,
        "automated_execution_allowed": False,
        "risk_sizing_verified": False,
        "orders_submitted": False,
    }
