"""Composition layer for conservative UTC-day cTrader realized P/L."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from .ctrader_deal_fee_validation import summarize_realized_close_deals_with_fee_check
from .ctrader_deal_pagination import fetch_complete_deal_history


async def realized_pl_for_utc_day(
    fetch_page: Callable[..., Awaitable[Any]],
    *,
    account_id: int,
    as_of: datetime | None = None,
    environment: str = "demo",
    max_rows: int = 1000,
    max_pages: int = 20,
) -> dict[str, Any]:
    """Calculate UTC-day realized P/L from complete, bounded demo history.

    Missing conversion-fee data withholds net P/L. This helper does not persist
    metrics or assert that the value is suitable for trading-risk checks.
    """
    if str(environment).strip().lower() != "demo":
        raise RuntimeError("Only cTrader demo accounts are enabled")
    instant = as_of or datetime.now(timezone.utc)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    instant = instant.astimezone(timezone.utc)
    start = instant.replace(hour=0, minute=0, second=0, microsecond=0)
    from_timestamp = int(start.timestamp() * 1000)
    to_timestamp = int(instant.timestamp() * 1000) + 1

    history = await fetch_complete_deal_history(
        fetch_page,
        account_id=account_id,
        from_timestamp=from_timestamp,
        to_timestamp=to_timestamp,
        environment="demo",
        max_rows=max_rows,
        max_pages=max_pages,
    )
    summary = summarize_realized_close_deals_with_fee_check(
        history, from_timestamp, to_timestamp
    )
    return {
        **summary,
        "metric": "realized_daily_pl",
        "window_timezone": "UTC",
        "window_start": start.isoformat(),
        "as_of": instant.isoformat(),
        "history_complete": True,
        "source": "ctrader_close_deal_history",
    }
