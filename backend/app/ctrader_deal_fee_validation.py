"""Conservative validation for cTrader realized P/L conversion fees."""
from __future__ import annotations

from typing import Any

from .ctrader_deal_history import summarize_realized_close_deals


def summarize_realized_close_deals_with_fee_check(
    response: Any, from_timestamp: int, to_timestamp: int
) -> dict[str, Any]:
    """Withhold net P/L when any closing deal's conversion-fee field is absent.

    The protobuf field is optional; absence is not silently interpreted as zero.
    This is intentionally conservative until the provider's omission semantics
    are confirmed for every supported account/symbol configuration.
    """
    summary = summarize_realized_close_deals(response, from_timestamp, to_timestamp)
    if not summary.get("close_deals_count"):
        return summary

    deals = getattr(response, "deal", None)
    missing_fee = False
    for deal in deals or []:
        timestamp = getattr(deal, "executionTimestamp", None)
        if (
            isinstance(timestamp, bool)
            or not isinstance(timestamp, int)
            or timestamp < from_timestamp
            or timestamp >= to_timestamp
        ):
            continue
        detail = getattr(deal, "closePositionDetail", None)
        if detail is None:
            continue
        has_field = getattr(detail, "HasField", None)
        if callable(has_field):
            try:
                present = bool(has_field("pnlConversionFee"))
            except (ValueError, TypeError):
                present = False
        else:
            present = getattr(detail, "pnlConversionFee", None) is not None
        if not present:
            missing_fee = True
            break

    if missing_fee:
        summary["pnl_conversion_fee"] = None
        summary["realized_net_pnl"] = None
        summary["status"] = "conversion_fee_unavailable_for_some_closing_deals"
    return summary
