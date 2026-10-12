"""Fail-closed policy for cTrader command execution."""


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
    """Return a block reason unless Demo and the sizing evidence are complete.

    A boolean flag alone is not enough to certify broker-specific sizing. The
    evidence must be tied to the selected account, environment and symbol.
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
    return None
