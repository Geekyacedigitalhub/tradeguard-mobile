"""Fail-closed pagination for bounded cTrader deal-history requests."""
from __future__ import annotations

from typing import Any, Awaitable, Callable


async def fetch_complete_deal_history(
    fetch_page: Callable[..., Awaitable[Any]],
    *,
    account_id: int,
    from_timestamp: int,
    to_timestamp: int,
    environment: str = "demo",
    max_rows: int = 1000,
    max_pages: int = 20,
) -> dict[str, Any]:
    """Fetch all pages or raise; never present a partial history as complete.

    Cursor advancement uses the greatest execution timestamp returned by a page.
    Deal IDs deduplicate overlap. If the provider says more data exists but the
    cursor cannot safely advance, this helper fails closed.
    """
    for name, value in (
        ("account_id", account_id),
        ("from_timestamp", from_timestamp),
        ("to_timestamp", to_timestamp),
        ("max_rows", max_rows),
        ("max_pages", max_pages),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} must be a positive integer")
    if to_timestamp <= from_timestamp or to_timestamp > 2147483646000:
        raise ValueError("Invalid cTrader deal-history time window")
    if max_rows > 1000 or max_pages > 20:
        raise ValueError("cTrader deal-history pagination limits exceeded")
    if str(environment).strip().lower() != "demo":
        raise RuntimeError("Only cTrader demo accounts are enabled")

    collected = []
    seen_ids: set[int] = set()
    cursor = from_timestamp

    for _ in range(max_pages):
        page = await fetch_page(
            account_id=account_id,
            from_timestamp=cursor,
            to_timestamp=to_timestamp,
            environment="demo",
            max_rows=max_rows,
        )
        page_deals = list(getattr(page, "deal", []) or [])
        for deal in page_deals:
            deal_id = getattr(deal, "dealId", None)
            if deal_id is not None:
                if isinstance(deal_id, bool) or not isinstance(deal_id, int) or deal_id <= 0:
                    raise ValueError("cTrader returned an invalid deal identifier")
                if deal_id in seen_ids:
                    continue
                seen_ids.add(deal_id)
            collected.append(deal)

        if not bool(getattr(page, "hasMore", False)):
            return {"deal": collected, "hasMore": False, "pages_fetched": _ + 1}

        timestamps = [
            getattr(deal, "executionTimestamp", None)
            for deal in page_deals
            if isinstance(getattr(deal, "executionTimestamp", None), int)
            and not isinstance(getattr(deal, "executionTimestamp", None), bool)
        ]
        if not timestamps:
            raise RuntimeError("cTrader deal-history pagination cannot advance safely")
        next_cursor = max(timestamps) + 1
        if next_cursor <= cursor or next_cursor >= to_timestamp:
            raise RuntimeError("cTrader deal-history pagination stalled before completion")
        cursor = next_cursor

    raise RuntimeError("cTrader deal history exceeded the safe pagination page limit")
