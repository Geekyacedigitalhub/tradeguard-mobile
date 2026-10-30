"""Broker-verified FX sizing evidence for automated cTrader entries.

Turns a signal (symbol, side, entry/stop/target, risk budget) into the
complete evidence contract required by ``ctrader_execution_guard.
entry_block_reason``. Every element comes from broker data fetched at
execution time; anything unverifiable fails closed with an actionable
reason and no order is submitted.

Instrument authorization: only symbols whose base AND quote assets are
broker assets whose name is exactly a curated ISO-4217 currency code are
treated as linear FX contracts (one base unit loses |entry - stop| units of
quote currency). Metals, indices, crypto, futures, and anything else stay
blocked. The codebase rule stands: never infer a contract type from a
symbol's display name.
"""
from __future__ import annotations

import math
from typing import Any

from .ctrader_conversion import convert_asset_amount
from .ctrader_risk_sizing import size_fx_volume_for_risk
from .ctrader_protection_validation import validate_positive_identifier

# Audited ISO-4217 currency codes. A broker asset counts as a verified
# currency only when its broker-provided asset name matches one of these
# exactly (ASCII, uppercase). Unknown codes fail closed.
VERIFIED_CURRENCY_ASSETS = frozenset({
    "AED", "ARS", "AUD", "BGN", "BHD", "BRL", "BSD", "BWP", "CAD", "CHF",
    "CLP", "CNY", "COP", "CZK", "DKK", "DOP", "EGP", "EUR", "FJD", "GBP",
    "HKD", "HRK", "HUF", "IDR", "ILS", "INR", "ISK", "JMD", "JPY", "KES",
    "KRW", "KWD", "KYD", "MAD", "MDL", "MXN", "MYR", "NAD", "NGN", "NOK",
    "NZD", "PAB", "PEN", "PHP", "PKR", "PLN", "QAR", "RON", "RSD", "RUB",
    "SAR", "SEK", "SGD", "THB", "TRY", "TTD", "TWD", "UAH", "UGX", "USD",
    "UYU", "VEF", "VND", "ZAR",
})


def is_verified_currency_asset(name: Any) -> bool:
    """Broker asset name must be exactly an audited ISO-4217 currency code.

    Exact match on purpose: no trimming, no case-folding. A broker that
    labels its currency asset anything other than the bare code (padding,
    lowercase, display names like "US DOLLAR") fails closed and stays
    outside automated execution.
    """
    if not isinstance(name, str) or not name.isascii():
        return False
    return name in VERIFIED_CURRENCY_ASSETS


def _valid_price(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
        and float(value) > 0
    )


def _side_price_consistency(trade_side: str, entry: float, stop: float, target: float) -> str | None:
    side = str(trade_side or "").strip().upper()
    if side not in ("BUY", "SELL"):
        return "Trade side must be BUY or SELL"
    if side == "BUY" and not (stop < entry < target):
        return "BUY entry must sit between its stop-loss and take-profit"
    if side == "SELL" and not (target < entry < stop):
        return "SELL entry must sit between its take-profit and stop-loss"
    return None


def entry_client_order_id(command_id: int, *, prefix: str = "TG") -> str:
    """Stable, broker-visible client order ID bound to one queued command."""
    command = validate_positive_identifier(command_id, "entry command id")
    return f"{prefix}{command:010d}E"


def find_symbol_in_catalog(catalog: Any, symbol_name: str) -> dict[str, Any] | None:
    """Match one exact, unambiguous, enabled symbol by broker name."""
    if not isinstance(symbol_name, str) or not symbol_name.strip():
        return None
    wanted = symbol_name.strip().upper()
    matches = []
    for row in catalog or []:
        if not isinstance(row, dict):
            continue
        name = row.get("symbol_name")
        if not isinstance(name, str) or name.strip().upper() != wanted:
            continue
        if row.get("enabled") is False:
            continue
        if not isinstance(row.get("symbol_id"), int) or isinstance(row.get("symbol_id"), bool) or row.get("symbol_id") <= 0:
            continue
        matches.append(row)
    if len(matches) != 1:
        return None
    return matches[0]


async def build_verified_sizing_evidence(
    *,
    manager: Any,
    user_id: str,
    account_id: int,
    environment: str,
    symbol_name: str,
    trade_side: str,
    entry_price: Any,
    stop_price: Any,
    target_price: Any,
    risk_budget_account_currency: Any,
    access_token: str,
    max_quote_age_ms: int = 5000,
) -> dict[str, Any]:
    """Assemble complete, fresh, broker-verified sizing evidence for one entry.

    Raises ``RuntimeError`` with an actionable reason when any element cannot
    be verified. Returns a dict with the full ``_REQUIRED_SIZING_EVIDENCE``
    contract plus ``order_params`` (raw volume, protection prices) for the
    caller to submit after ``entry_block_reason`` accepts the evidence.
    """
    if str(environment or "").strip().lower() != "demo":
        raise RuntimeError("Automated entries are disabled for cTrader Live accounts; select a Demo account")
    for field, value in (("entry_price", entry_price), ("stop_price", stop_price),
                         ("target_price", target_price),
                         ("risk_budget_account_currency", risk_budget_account_currency)):
        if not _valid_price(value):
            raise RuntimeError(f"Automated entry blocked: {field} must be a positive finite number")
    entry, stop, target = float(entry_price), float(stop_price), float(target_price)
    side_reason = _side_price_consistency(trade_side, entry, stop, target)
    if side_reason:
        raise RuntimeError(f"Automated entry blocked: {side_reason}")
    budget = float(risk_budget_account_currency)

    # 1) Broker account identity and deposit-currency asset.
    trader = await manager.trader(account_id, environment)
    deposit_asset_id = getattr(trader, "depositAssetId", None)
    if isinstance(deposit_asset_id, bool) or not isinstance(deposit_asset_id, int) or deposit_asset_id <= 0:
        raise RuntimeError("Automated entry blocked: broker deposit-currency asset ID is unavailable")

    # 2) Symbol identity from the broker catalogue (name + asset IDs).
    catalog = await manager.symbol_catalog(account_id, environment)
    symbol_row = find_symbol_in_catalog(catalog, symbol_name)
    if symbol_row is None:
        raise RuntimeError(
            f"Automated entry blocked: symbol {symbol_name!r} has no exact, unambiguous, enabled broker match"
        )
    symbol_id = symbol_row["symbol_id"]
    base_asset_id = symbol_row.get("base_asset_id")
    quote_asset_id = symbol_row.get("quote_asset_id")
    if (isinstance(base_asset_id, bool) or not isinstance(base_asset_id, int) or base_asset_id <= 0
            or isinstance(quote_asset_id, bool) or not isinstance(quote_asset_id, int) or quote_asset_id <= 0):
        raise RuntimeError("Automated entry blocked: broker base/quote asset identity is unavailable")
    if base_asset_id == quote_asset_id:
        raise RuntimeError("Automated entry blocked: broker base and quote assets are identical")

    # 3) Broker contract metadata for this exact symbol ID.
    product = await manager.symbol_product(account_id, symbol_id, environment)

    # 4) Instrument authorization from broker asset names (audited currency
    #    codes only). Everything else stays blocked by design.
    assets = await manager.asset_catalog(account_id, environment)
    base_name = assets.get(base_asset_id)
    quote_name = assets.get(quote_asset_id)
    deposit_name = assets.get(deposit_asset_id)
    if base_name is None or quote_name is None or deposit_name is None:
        raise RuntimeError("Automated entry blocked: broker asset metadata is incomplete for this symbol")
    if not is_verified_currency_asset(base_name) or not is_verified_currency_asset(quote_name):
        raise RuntimeError(
            "Automated entry blocked: verified sizing currently supports FX instruments only "
            f"(broker assets {base_name!r}/{quote_name!r} are not audited currency assets)"
        )
    if not is_verified_currency_asset(deposit_name):
        raise RuntimeError(
            f"Automated entry blocked: broker deposit asset {deposit_name!r} is not an audited currency asset"
        )

    # 5) Fresh, executable-side conversion quotes (quote currency -> deposit).
    now_ms = _now_ms()
    conversion_symbols: list[dict[str, Any]] = []
    quotes_by_symbol_id: dict[int, dict[str, Any]] = {}
    if quote_asset_id != deposit_asset_id:
        conv = await manager.symbols_for_conversion(account_id, quote_asset_id, deposit_asset_id, environment)
        conversion_symbols = list(conv.get("symbols") or [])
        if not conversion_symbols:
            raise RuntimeError(
                "Automated entry blocked: broker returned no conversion path from the traded quote asset to the deposit asset"
            )
        snapshot = await manager.subscribe_conversion_quotes(
            str(user_id), account_id, conversion_symbols, access_token, environment
        )
        quotes_by_symbol_id = dict(snapshot.get("quotes_by_symbol_id") or {})
        now_ms = int(snapshot.get("snapshot_timestamp_ms") or now_ms)

    # 6) Risk sizing against broker volume constraints.
    try:
        sizing = size_fx_volume_for_risk(
            risk_budget_account_currency=budget,
            entry_price=entry,
            stop_price=stop,
            trade_side=str(trade_side).strip().upper(),
            base_asset_id=base_asset_id,
            quote_asset_id=quote_asset_id,
            account_asset_id=deposit_asset_id,
            conversion_symbols=conversion_symbols,
            quotes_by_symbol_id=quotes_by_symbol_id,
            now_timestamp_ms=now_ms,
            min_volume=product["min_volume"],
            max_volume=product["max_volume"],
            step_volume=product["step_volume"],
            max_quote_age_ms=max_quote_age_ms,
        )
    except (ValueError, ArithmeticError) as exc:
        # Stale/crossed quotes, unquotable paths, and budgets below the broker
        # minimum all surface as one actionable block reason.
        raise RuntimeError(f"Automated entry blocked: {exc}") from exc

    # 7) Loss per 1.00 price unit per traded unit (1 raw volume = 0.01 base
    #    unit), expressed in deposit currency, from the same verified quotes.
    if quote_asset_id == deposit_asset_id:
        unit_loss = 1.0
        path_symbols: list[int] = []
        path_timestamps: list[int] = []
    else:
        try:
            unit_conversion = convert_asset_amount(
                1.0, quote_asset_id, deposit_asset_id,
                conversion_symbols=conversion_symbols,
                quotes_by_symbol_id=quotes_by_symbol_id,
                now_timestamp_ms=now_ms,
                max_quote_age_ms=max_quote_age_ms,
            )
        except (ValueError, ArithmeticError) as exc:
            raise RuntimeError(f"Automated entry blocked: {exc}") from exc
        unit_loss = float(unit_conversion["rate"])
        path_symbols = [int(step["symbol_id"]) for step in unit_conversion["path"]]
        path_timestamps = [int(t) for t in unit_conversion["quote_timestamps_ms"]]
    if not math.isfinite(unit_loss) or unit_loss <= 0:
        raise RuntimeError("Automated entry blocked: deposit-currency loss per price unit is invalid")

    stop_distance = abs(entry - stop)
    volume = int(sizing["volume_raw"])
    estimated_loss = float(sizing["estimated_loss_account_currency"])
    if not math.isfinite(estimated_loss) or estimated_loss <= 0:
        raise RuntimeError("Automated entry blocked: estimated stop-loss value is invalid")
    if estimated_loss > budget:
        raise RuntimeError("Automated entry blocked: no broker volume fits within the configured risk budget")

    evidence = {
        "account_id": int(account_id),
        "environment": "demo",
        "symbol_id": int(symbol_id),
        "symbol_name": symbol_row.get("symbol_name"),
        "contract_size": int(product["lot_size"]),
        "instrument_type": "FX",
        "contract_model": "linear_fx_base_units",
        "base_asset_id": int(base_asset_id),
        "quote_asset_id": int(quote_asset_id),
        "deposit_asset_id": int(deposit_asset_id),
        "stop_loss_side_validated": True,
        "account_currency": str(deposit_name).strip().upper(),
        "conversion_verified": True,
        "conversion_source_asset_id": int(quote_asset_id),
        "conversion_target_asset_id": int(deposit_asset_id),
        "conversion_path_symbol_ids": path_symbols,
        "conversion_quote_timestamps_ms": path_timestamps,
        "loss_per_price_unit_per_traded_unit": unit_loss,
        "stop_distance": stop_distance,
        "risk_amount": float(budget),
        "broker_volume": volume,
        "min_volume": int(product["min_volume"]),
        "max_volume": int(product["max_volume"]),
        "step_volume": int(product["step_volume"]),
        "estimated_loss_account_currency": estimated_loss,
        "risk_sizing_verified": True,
        "requires_broker_specific_contract_verification": False,
    }
    evidence["order_params"] = {
        "volume": volume,
        "stop_loss": stop,
        "take_profit": target,
        "client_order_id": None,  # filled by the caller (bound to the command id)
    }
    return evidence


def _now_ms() -> int:
    import time

    return int(time.time() * 1000)
