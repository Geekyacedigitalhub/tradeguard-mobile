"""Fail-closed policy for cTrader command execution."""

import math


_REQUIRED_SIZING_EVIDENCE = (
    "account_id",
    "environment",
    "symbol_id",
    "contract_size",
    "account_currency",
    "loss_per_price_unit_per_traded_unit",
    "stop_distance",
    "risk_amount",
    "broker_volume",
    "min_volume",
    "max_volume",
    "step_volume",
)


def entry_block_reason(
    environment: str,
    *,
    sizing_verified: bool = False,
    sizing_evidence=None,
    expected_account_id=None,
    expected_symbol_id=None,
) -> str | None:
    """Return a block reason unless Demo sizing evidence is complete and consistent.

    The caller must obtain the monetary value and conversion from verified
    broker/instrument data. This guard checks evidence consistency; it cannot
    itself prove that a supplied conversion is correct.
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
    if not str(sizing_evidence.get("account_id", "")).strip() or not str(sizing_evidence.get("symbol_id", "")).strip():
        return "Automated entry blocked: risk-sizing evidence is not tied to a selected account and symbol"
    if expected_account_id is None or expected_symbol_id is None:
        return "Automated entry blocked: selected account and symbol identity were not independently supplied"
    if str(sizing_evidence["account_id"]).strip() != str(expected_account_id).strip():
        return "Automated entry blocked: risk-sizing evidence account does not match the selected account"
    if str(sizing_evidence["symbol_id"]).strip() != str(expected_symbol_id).strip():
        return "Automated entry blocked: risk-sizing evidence symbol does not match the selected symbol"
    if not str(sizing_evidence.get("account_currency", "")).strip():
        return "Automated entry blocked: account currency is missing"
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
    if minimum <= 0 or maximum < minimum or step <= 0 or volume < minimum or volume > maximum:
        return "Automated entry blocked: broker volume constraints are invalid"
    if (volume - minimum) % step != 0:
        return "Automated entry blocked: broker volume does not align to the symbol's volume step"
    estimated_risk = (volume / 100.0) * stop_distance * unit_loss
    if not math.isfinite(estimated_risk) or estimated_risk > risk_amount + max(1e-9, risk_amount * 1e-12):
        return "Automated entry blocked: calculated risk exceeds the approved risk amount"
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
    if command_type not in ("open_market", "close_position", "protect_position"):
        return f"cTrader command blocked: unsupported command {command_type}"
    if command_type == "close_position" and not (
        isinstance(payload, dict) and payload.get("manual_close") is True
    ):
        return "cTrader close blocked: explicit manual-close authorization is required"
    if normalized_environment == "live" and command_type != "close_position":
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
