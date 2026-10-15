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

    Timestamp cursors remain inclusive to avoid skipping same-millisecond deals.
    Stable IDs deduplicate overlap. Every returned row is validated against the
    requested window and configured page bound before it can enter the result.
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

    for page_number in range(1, max_pages + 1):
        page = await fetch_page(
            account_id=account_id,
            from_timestamp=cursor,
            to_timestamp=to_timestamp,
            environment="demo",
            max_rows=max_rows,
        )
        page_deals = list(getattr(page, "deal", []) or [])
        if len(page_deals) > max_rows:
            raise RuntimeError("cTrader returned more deals than the requested page limit")
        has_more = bool(getattr(page, "hasMore", False))
        new_deal_ids = 0
        timestamps: list[int] = []

        for deal in page_deals:
            timestamp = getattr(deal, "executionTimestamp", None)
            if isinstance(timestamp, bool) or not isinstance(timestamp, int):
                raise RuntimeError("cTrader deal is missing a valid execution timestamp")
            if timestamp < from_timestamp or timestamp >= to_timestamp:
                raise RuntimeError("cTrader returned a deal outside the requested time window")
            timestamps.append(timestamp)

            deal_id = getattr(deal, "dealId", None)
            if deal_id is None:
                if has_more:
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

        if len(collected) > max_rows * max_pages:
            raise RuntimeError("cTrader deal history exceeded the safe total-row limit")
        if not has_more:
            return {"deal": collected, "hasMore": False, "pages_fetched": page_number}
        if not timestamps or new_deal_ids == 0:
            raise RuntimeError("cTrader deal-history pagination stalled before completion")

        # Keep the timestamp inclusive. Advancing by +1 could skip other deals
        # sharing the page's final millisecond; stable deal IDs deduplicate overlap.
        next_cursor = max(timestamps)
        if next_cursor < cursor or next_cursor >= to_timestamp:
            raise RuntimeError("cTrader deal-history pagination stalled before completion")
        cursor = next_cursor

    raise RuntimeError("cTrader deal history exceeded the safe pagination page limit")
