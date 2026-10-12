"""Fail-closed policy for cTrader command execution."""


def entry_block_reason(environment: str, *, sizing_verified: bool = False) -> str | None:
    """Return a user-safe block reason unless every execution prerequisite is met."""
    if str(environment or "").lower() != "demo":
        return "Automated orders are disabled for cTrader Live accounts; select a Demo account"
    if not sizing_verified:
        return (
            "Automated entries are paused until broker-verified account-currency "
            "risk sizing is connected and tested for this symbol and account"
        )
    return None
