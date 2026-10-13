"""Fail-closed policy for cTrader command execution."""

import math
import time


_REQUIRED_SIZING_EVIDENCE = (
    "account_id",
    "environment",
    "symbol_id",
    "contract_size",
    "instrument_type",
    "contract_model",
    "base_asset_id",
    "quote_asset_id",
    "deposit_asset_id",
    "stop_loss_side_validated",
    "account_currency",
    "conversion_verified",
    "conversion_source_asset_id",
    "conversion_target_asset_id",
    "conversion_path_symbol_ids",
    "conversion_quote_timestamps_ms",
    "loss_per_price_unit_per_traded_unit",
    "stop_distance",
    "risk_amount",
    "broker_volume",
    "min_volume",
    "max_volume",
    "step_volume",
)


_MAX_PROTOCOL_ID = (1 << 63) - 1


def _valid_identity(value):
    """Accept positive signed-64-bit IDs or decimal strings only."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return 0 < value <= _MAX_PROTOCOL_ID
    if isinstance(value, str):
        normalized = value.strip()
        # cTrader protocol identifiers are signed 64-bit integers. Bound the
        # digit count before parsing to avoid pathological inputs and int limits.
        if (
            not normalized
            or len(normalized) > 19
            or not normalized.isascii()
            or not normalized.isdecimal()
        ):
            return False
        try:
            parsed = int(normalized)
        except (ValueError, OverflowError):
            return False
        return 0 < parsed <= _MAX_PROTOCOL_ID
    return False


def entry_block_reason(
    environment: str,
    *,
    sizing_verified: bool = False,
    sizing_evidence=None,
    expected_account_id=None,
    expected_symbol_id=None,
) -> str | None:
    """Return a block reason unless Demo sizing evidence is complete and consistent.

    The caller must obtain monetary value and conversion from broker data.
    This guard checks identity, quote freshness, and evidence shape, but it
    cannot independently prove the broker calculation itself is correct.
    """
    normalized_environment = str(environment or "").strip().lower()
    if normalized_environment != "demo":
        return "Automated orders are disabled for cTrader Live accounts; select a Demo account"
    if sizing_verified is not True or not isinstance(sizing_evidence, dict):
        return (
            "Automated entries are paused until broker-verified account-currency "
            "risk sizing is connected and tested for this symbol and account"
        )
    if any(key not in sizing_evidence or sizing_evidence[key] is None for key in _REQUIRED_SIZING_EVIDENCE):
        return "Automated entry blocked: broker risk-sizing evidence is incomplete"
    if str(sizing_evidence.get("environment", "")).strip().lower() != normalized_environment:
        return "Automated entry blocked: risk-sizing evidence environment does not match the selected account"
    if not _valid_identity(sizing_evidence.get("account_id")) or not _valid_identity(sizing_evidence.get("symbol_id")):
        return "Automated entry blocked: risk-sizing evidence account and symbol IDs must be positive integer identifiers"
    if not _valid_identity(expected_account_id) or not _valid_identity(expected_symbol_id):
        return "Automated entry blocked: selected account and symbol identity must be valid positive integer identifiers"
    if str(sizing_evidence["account_id"]).strip() != str(expected_account_id).strip():
        return "Automated entry blocked: risk-sizing evidence account does not match the selected account"
    if str(sizing_evidence["symbol_id"]).strip() != str(expected_symbol_id).strip():
        return "Automated entry blocked: risk-sizing evidence symbol does not match the selected symbol"
    if not str(sizing_evidence.get("account_currency", "")).strip():
        return "Automated entry blocked: account currency is missing"
    # The current calculator is defined only for linear FX base-unit contracts.
    # Do not let a generic "verified" flag authorize metals, indices, crypto,
    # futures, or CFDs with broker-specific contract multipliers.
    if str(sizing_evidence.get("instrument_type", "")).strip().upper() != "FX":
        return "Automated entry blocked: verified sizing currently supports FX instruments only"
    if str(sizing_evidence.get("contract_model", "")).strip() != "linear_fx_base_units":
        return "Automated entry blocked: broker contract model is not verified for linear FX base units"
    if sizing_evidence.get("stop_loss_side_validated") is not True:
        return "Automated entry blocked: stop-loss direction has not been validated for the trade side"
    contract_asset_ids = (
        sizing_evidence.get("base_asset_id"),
        sizing_evidence.get("quote_asset_id"),
        sizing_evidence.get("deposit_asset_id"),
    )
    if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 or value > _MAX_PROTOCOL_ID for value in contract_asset_ids):
        return "Automated entry blocked: broker base, quote, or deposit asset identity is invalid"
    if contract_asset_ids[0] == contract_asset_ids[1]:
        return "Automated entry blocked: broker FX base and quote assets must differ"
    asset_ids = (
        sizing_evidence.get("conversion_source_asset_id"),
        sizing_evidence.get("conversion_target_asset_id"),
    )
    if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 or value > _MAX_PROTOCOL_ID for value in asset_ids):
        return "Automated entry blocked: conversion asset identity is invalid"
    if asset_ids[0] != contract_asset_ids[1]:
        return "Automated entry blocked: conversion source does not match the traded FX quote asset"
    if asset_ids[1] != contract_asset_ids[2]:
        return "Automated entry blocked: conversion target does not match the broker deposit asset"
    if sizing_evidence.get("conversion_verified") is not True:
        return "Automated entry blocked: account-currency conversion is not verified"
    path_ids = sizing_evidence.get("conversion_path_symbol_ids")
    timestamps = sizing_evidence.get("conversion_quote_timestamps_ms")
    if not isinstance(path_ids, list) or not isinstance(timestamps, list) or len(path_ids) != len(timestamps):
        return "Automated entry blocked: conversion quote evidence is incomplete"
    if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 or value > _MAX_PROTOCOL_ID for value in path_ids):
        return "Automated entry blocked: conversion path contains invalid symbol IDs"
    if len(set(path_ids)) != len(path_ids):
        return "Automated entry blocked: conversion path repeats a broker symbol ID"
    now_ms = int(time.time() * 1000)
    for timestamp in timestamps:
        if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp <= 0:
            return "Automated entry blocked: conversion quote timestamp is invalid"
        age_ms = now_ms - timestamp
        if age_ms < 0 or age_ms > 5000:
            return "Automated entry blocked: conversion quotes must be fresh (maximum age 5 seconds)"
    if asset_ids[0] != asset_ids[1] and not path_ids:
        return "Automated entry blocked: cross-asset conversion has no quoted broker path"
    if asset_ids[0] == asset_ids[1] and path_ids:
        return "Automated entry blocked: same-asset conversion must not include a conversion path"
    volume_fields = ("broker_volume", "min_volume", "max_volume", "step_volume")
    if any(
        isinstance(sizing_evidence[key], bool) or not isinstance(sizing_evidence[key], int)
        for key in volume_fields
    ):
        return "Automated entry blocked: broker volume constraints must be integer protocol values"
    numeric_fields = (
        "contract_size",
        "loss_per_price_unit_per_traded_unit",
        "stop_distance",
        "risk_amount",
    )
    if any(
        isinstance(sizing_evidence[key], bool)
        or not isinstance(sizing_evidence[key], (int, float))
        for key in numeric_fields
    ):
        return "Automated entry blocked: risk-sizing numeric evidence must be numeric values, not booleans or strings"
    try:
        contract_size = float(sizing_evidence["contract_size"])
        unit_loss = float(sizing_evidence["loss_per_price_unit_per_traded_unit"])
        stop_distance = float(sizing_evidence["stop_distance"])
        risk_amount = float(sizing_evidence["risk_amount"])
        volume = sizing_evidence["broker_volume"]
        minimum = sizing_evidence["min_volume"]
        maximum = sizing_evidence["max_volume"]
        step = sizing_evidence["step_volume"]
    except (TypeError, ValueError, OverflowError):
        return "Automated entry blocked: risk-sizing evidence contains invalid numeric values"
    if any(not math.isfinite(value) or value <= 0 for value in (contract_size, unit_loss, stop_distance, risk_amount)):
        return "Automated entry blocked: risk-sizing evidence contains non-positive or non-finite values"
    if any(value > _MAX_PROTOCOL_ID for value in (volume, minimum, maximum, step)):
        return "Automated entry blocked: broker volume constraints exceed the cTrader protocol range"
    if minimum <= 0 or maximum < minimum or step <= 0 or volume < minimum or volume > maximum:
        return "Automated entry blocked: broker volume constraints are invalid"
    if (volume - minimum) % step != 0:
        return "Automated entry blocked: broker volume does not align to the symbol's volume step"
    try:
        estimated_risk = (volume / 100.0) * stop_distance * unit_loss
    except (OverflowError, ValueError):
        return "Automated entry blocked: calculated risk is outside the supported numeric range"
    if not math.isfinite(estimated_risk) or estimated_risk > risk_amount + max(1e-9, risk_amount * 1e-12):
        return "Automated entry blocked: calculated risk exceeds the approved risk amount"
    return None



def bot_entry_block_reason(running, emergency_stopped) -> str | None:
    """Prevent queued automated entries when the bot is stopped or emergency-locked."""
    if emergency_stopped is not False:
        return "cTrader entry blocked: emergency stop is active or its state is unknown"
    if running is not True:
        return "cTrader entry blocked: bot is not running"
    return None


def command_block_reason(environment: str, command_type: str, payload=None) -> str | None:
    """Validate account environment and explicit manual-close intent before execution.

    Every close must originate from an authenticated manual control. Live
    commands are further restricted to manual closes; entries and protection
    amendments remain disabled for Live until independently verified.
    """
    normalized_environment = str(environment or "").strip().lower()
    if normalized_environment not in ("demo", "live"):
        return "cTrader command blocked: selected account environment is invalid"
    if command_type not in ("open_market", "close_position", "close_all_positions", "protect_position"):
        return f"cTrader command blocked: unsupported command {command_type}"
    if command_type in ("close_position", "close_all_positions") and not (
        isinstance(payload, dict) and payload.get("manual_close") is True
    ):
        return "cTrader close blocked: explicit manual-close authorization is required"
    if normalized_environment == "live" and command_type not in ("close_position", "close_all_positions"):
        return "Live cTrader permits manual position closes only; automated entries and position amendments remain disabled"
    return None



def close_binding_block_reason(environment: str, selected_account_id, payload=None) -> str | None:
    """Reject queued closes not bound to the currently selected account and environment."""
    if not isinstance(payload, dict):
        return "cTrader close blocked: command payload is missing"
    queued_account_id = payload.get("account_id")
    if (
        isinstance(queued_account_id, bool)
        or not isinstance(queued_account_id, int)
        or queued_account_id <= 0
        or isinstance(selected_account_id, bool)
        or not isinstance(selected_account_id, int)
        or selected_account_id <= 0
    ):
        return "cTrader close blocked: valid selected account binding is required"
    if queued_account_id != selected_account_id:
        return "cTrader close blocked: selected account changed after the close was queued"
    queued_environment = payload.get("environment")
    if not isinstance(queued_environment, str) or queued_environment.strip().lower() != str(environment or "").strip().lower():
        return "cTrader close blocked: selected account environment changed or was not bound when queued"
    return None
