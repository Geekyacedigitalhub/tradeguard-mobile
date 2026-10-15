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
        new_deal_ids = 0
        for deal in page_deals:
            deal_id = getattr(deal, "dealId", None)
            if deal_id is None:
                if bool(getattr(page, "hasMore", False)):
                    raise RuntimeError("Cannot safely paginate cTrader history without stable deal IDs")
                collected.append(deal)
                continue
            if isinstance(deal_id, bool) or not isinstance(deal_id, int) or deal_id <= 0:
                raise ValueError("cTrader returned an invalid deal identifier")
            if deal_id in seen_ids:
                continue
            seen_ids.add(deal_id)
            new_deal_ids += 1
            collected.append(deal)

        if not bool(getattr(page, "hasMore", False)):
            return {"deal": collected, "hasMore": False, "pages_fetched": _ + 1}

        timestamps = [
            getattr(deal, "executionTimestamp", None)
            for deal in page_deals
            if isinstance(getattr(deal, "executionTimestamp", None), int)
            and not isinstance(getattr(deal, "executionTimestamp", None), bool)
        ]
        if not timestamps or new_deal_ids == 0:
            raise RuntimeError("cTrader deal-history pagination stalled before completion")
        # Keep the timestamp inclusive. Advancing by +1 could skip other deals
        # sharing the page's final millisecond; stable deal IDs deduplicate overlap.
        next_cursor = max(timestamps)
        if next_cursor < cursor or next_cursor >= to_timestamp:
            raise RuntimeError("cTrader deal-history pagination stalled before completion")
        cursor = next_cursor

    raise RuntimeError("cTrader deal history exceeded the safe pagination page limit")
