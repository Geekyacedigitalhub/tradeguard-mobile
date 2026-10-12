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


def entry_block_reason(environment: str, *, sizing_verified: bool = False, sizing_evidence=None) -> str | None:
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
    if not str(sizing_evidence.get("account_currency", "")).strip():
        return "Automated entry blocked: account currency is missing"
    try:
        contract_size = float(sizing_evidence["contract_size"])
        unit_loss = float(sizing_evidence["loss_per_price_unit_per_traded_unit"])
        stop_distance = float(sizing_evidence["stop_distance"])
        risk_amount = float(sizing_evidence["risk_amount"])
        volume = int(sizing_evidence["broker_volume"])
        minimum = int(sizing_evidence["min_volume"])
        maximum = int(sizing_evidence["max_volume"])
        step = int(sizing_evidence["step_volume"])
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
