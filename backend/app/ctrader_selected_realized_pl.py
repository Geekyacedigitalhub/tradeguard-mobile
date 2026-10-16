"""Adapter for the selected cTrader demo account's realized P/L."""
from datetime import datetime
from typing import Any

from .ctrader_realized_metrics import realized_pl_for_utc_day
from .ctrader_service import manager
from .ctrader_snapshot_helpers import positive_integer
from .db import connection


async def selected_account_realized_pl(user_id: str, *, as_of: datetime | None = None) -> dict[str, Any]:
    with connection() as conn:
        row = conn.execute(
            "SELECT account_id,environment FROM ctrader_connections WHERE user_id=%s",
            (user_id,),
        ).fetchone()
    if not row or not row[0]:
        raise RuntimeError("Select a cTrader demo account first.")
    account_id = positive_integer(row[0])
    if account_id is None:
        raise RuntimeError("The selected cTrader account identifier is invalid.")
    if str(row[1] or "demo").strip().lower() != "demo":
        raise RuntimeError("Only cTrader demo accounts are enabled.")
    if not manager.account_ready("demo", account_id):
        raise RuntimeError("The selected cTrader demo account is not connected.")

    async def fetch_page(**kwargs):
        if kwargs.get("account_id") != account_id or kwargs.get("environment") != "demo":
            raise RuntimeError("History request does not match the selected demo account.")
        if not manager.account_ready("demo", account_id):
            raise RuntimeError("The selected cTrader demo account disconnected.")
        return await manager.deals(
            account_id=account_id,
            from_timestamp=kwargs["from_timestamp"],
            to_timestamp=kwargs["to_timestamp"],
            environment="demo",
            max_rows=kwargs["max_rows"],
        )

    result = await realized_pl_for_utc_day(
        fetch_page, account_id=account_id, as_of=as_of, environment="demo"
    )

    # The account selection can change while paginated history is being fetched.
    # Re-read it after the await and fail closed rather than returning stale-account
    # P/L under the user's newly selected account.
    with connection() as conn:
        current = conn.execute(
            "SELECT account_id,environment FROM ctrader_connections WHERE user_id=%s",
            (user_id,),
        ).fetchone()
    if (
        not current
        or current[0] is None
        or positive_integer(current[0]) != account_id
        or str(current[1] or "demo").strip().lower() != "demo"
        or not manager.account_ready("demo", account_id)
    ):
        raise RuntimeError(
            "Selected cTrader demo account changed or disconnected during history retrieval."
        )

    return {
        **result,
        "account_id": account_id,
        "environment": "demo",
        "provider": "cTrader Cloud",
        "risk_metrics_verified": False,
        "risk_metrics_status": "calculation_only_not_persisted_or_risk_verified",
    }
