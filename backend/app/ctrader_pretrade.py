"""Read-only pre-trade readiness checks for cTrader.

This layer reports what is missing; it does not approve sizing or submit orders.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any


_MAX_PROTOCOL_ID = (1 << 63) - 1


def _valid_protocol_id(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, int)
        and 0 < value <= _MAX_PROTOCOL_ID
    )


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
    if not _valid_protocol_id(account_id):
        blockers.append("Selected account identity is invalid.")
    normalized_environment = str(environment or "").strip().lower()
    if normalized_environment not in ("demo", "live"):
        blockers.append("Selected account environment is unknown.")
    if normalized_environment == "live":
        blockers.append("Automated entries on Live accounts are disabled.")
    if not _valid_protocol_id(deposit_asset_id):
        blockers.append("Broker deposit-currency asset ID is unavailable.")
    if not isinstance(symbol, Mapping):
        symbol = {}
        blockers.append("Broker symbol metadata is unavailable.")
    symbol_id = symbol.get("symbol_id")
    if not _valid_protocol_id(symbol_id):
        blockers.append("Broker symbol ID is invalid.")
    base_id = symbol.get("base_asset_id")
    quote_id = symbol.get("quote_asset_id")
    for field, value in (("base", base_id), ("quote", quote_id)):
        if not _valid_protocol_id(value):
            blockers.append(f"Broker {field}-asset ID is unavailable.")
    if _valid_protocol_id(base_id) and _valid_protocol_id(quote_id) and base_id == quote_id:
        blockers.append("Broker base and quote assets are identical.")
    if symbol.get("volume_constraints_valid") is not True:
        blockers.append("Broker minimum, maximum, and step-volume constraints are not valid.")
    if symbol.get("instrument_type") != "FX" or symbol.get("contract_model") != "linear_fx_base_units":
        blockers.append("Broker has not verified this symbol as a supported linear FX contract.")
    if symbol.get("risk_sizing_verified") is not True:
        blockers.append("Broker-specific account-currency risk sizing has not been verified for this symbol.")
    side = trade_side.upper() if isinstance(trade_side, str) else ""
    if side not in ("BUY", "SELL"):
        blockers.append("Trade side must be BUY or SELL.")
    # Broker payloads are untrusted: converting an arbitrarily large Python
    # integer to float can raise OverflowError. A malformed price must become
    # a readiness blocker, never crash the preflight endpoint.
    valid_prices = False
    try:
        if (
            not isinstance(entry_price, bool) and isinstance(entry_price, (int, float))
            and not isinstance(stop_price, bool) and isinstance(stop_price, (int, float))
        ):
            entry_value = float(entry_price)
            stop_value = float(stop_price)
            valid_prices = (
                math.isfinite(entry_value) and math.isfinite(stop_value)
                and entry_value > 0 and stop_value > 0
            )
    except (OverflowError, ValueError):
        valid_prices = False
    if not valid_prices:
        blockers.append("Entry and stop-loss prices must be positive finite numbers.")
    elif side == "BUY" and float(stop_price) >= float(entry_price):
        blockers.append("BUY stop-loss must be below entry price.")
    elif side == "SELL" and float(stop_price) <= float(entry_price):
        blockers.append("SELL stop-loss must be above entry price.")
    if _valid_protocol_id(quote_id) and _valid_protocol_id(deposit_asset_id):
        if quote_id != deposit_asset_id:
            blockers.append("Account-currency conversion quotes have not been verified for this preflight.")
    return {
        "ready": not blockers,
        "status": "ready" if not blockers else "blocked",
        "blockers": blockers,
        "account_id": account_id if _valid_protocol_id(account_id) else None,
        "environment": normalized_environment or None,
        "symbol_id": symbol_id if _valid_protocol_id(symbol_id) else None,
        "symbol_name": symbol.get("symbol_name") if isinstance(symbol.get("symbol_name"), str) else None,
        "trade_side": side or None,
        "automated_execution_allowed": False,
        "risk_sizing_verified": False,
        "orders_submitted": False,
    }
