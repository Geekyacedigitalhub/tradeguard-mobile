"""Strict normalization for cTrader close-deal financial components.

This module intentionally exposes components rather than inventing a net P/L
formula. Broker-supplied values remain scaled integers until their precision
and presence are validated.
"""
from __future__ import annotations

import math
from typing import Any


def _required_integer(source: Any, field: str) -> int:
    value = getattr(source, field, None)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"cTrader close-deal {field} is unavailable or invalid")
    return value


def _optional_integer(source: Any, field: str) -> int | None:
    has_field = getattr(source, "HasField", None)
    if callable(has_field):
        try:
            if not has_field(field):
                return None
        except (ValueError, TypeError):
            return None
    value = getattr(source, field, None)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"cTrader close-deal {field} is invalid")
    return value


def _has_message(source: Any, field: str) -> bool:
    has_field = getattr(source, "HasField", None)
    if callable(has_field):
        try:
            return bool(has_field(field))
        except (ValueError, TypeError):
            return False
    return getattr(source, field, None) is not None


def normalize_close_deal(deal: Any) -> dict[str, int | float | None]:
    """Return validated scaled components for a broker-reported closing deal.

    This does not aggregate P/L. A closePositionDetail is only present on
    closing deals, and moneyDigits is required to interpret its integer amounts.
    """
    if not _has_message(deal, "closePositionDetail"):
        raise ValueError("cTrader deal has no closing-position details")
    detail = getattr(deal, "closePositionDetail", None)
    if detail is None:
        raise ValueError("cTrader deal has no closing-position details")

    money_digits = _optional_integer(detail, "moneyDigits")
    if money_digits is None or money_digits < 0 or money_digits > 8:
        raise ValueError("cTrader close-deal moneyDigits is unavailable or invalid")

    gross_profit = _required_integer(detail, "grossProfit")
    swap = _required_integer(detail, "swap")
    commission = _required_integer(detail, "commission")
    conversion_fee = _optional_integer(detail, "pnlConversionFee")
    scale = 10 ** money_digits

    components = (gross_profit, swap, commission)
    if any(not math.isfinite(float(value)) for value in components):
        raise ValueError("cTrader close-deal financial component is not finite")

    return {
        "money_digits": money_digits,
        "gross_profit": gross_profit / scale,
        "swap": swap / scale,
        "commission": commission / scale,
        "pnl_conversion_fee": conversion_fee / scale if conversion_fee is not None else None,
    }


def summarize_realized_close_deals(
    response: Any, from_timestamp: int, to_timestamp: int
) -> dict[str, int | float | None]:
    """Summarize a complete broker history page for a bounded UTC-ms window.

    Refuses partial pages: a partial history cannot support a reliable daily
    realized P/L metric. Non-closing deals are ignored; closing deals must have
    valid execution timestamps and complete required financial components.
    """
    from_timestamp = _positive_timestamp(from_timestamp, "from_timestamp")
    to_timestamp = _positive_timestamp(to_timestamp, "to_timestamp")
    if to_timestamp <= from_timestamp:
        raise ValueError("Invalid cTrader deal-history time window")
    if bool(getattr(response, "hasMore", False)):
        raise ValueError("cTrader deal history is incomplete; fetch remaining pages")

    deals = getattr(response, "deal", None)
    if deals is None:
        raise ValueError("cTrader deal history response has no deal collection")

    totals: dict[str, int] = {
        "gross_profit": 0,
        "swap": 0,
        "commission": 0,
        "pnl_conversion_fee": 0,
    }
    digits: int | None = None
    close_count = 0

    for deal in deals:
        if not _has_message(deal, "closePositionDetail"):
            continue
        detail = getattr(deal, "closePositionDetail", None)
        if detail is None:
            continue
        timestamp = _optional_integer(deal, "executionTimestamp")
        if timestamp is None or timestamp < from_timestamp or timestamp >= to_timestamp:
            raise ValueError("Closing deal timestamp is missing or outside requested window")
        normalize_close_deal(deal)  # validate presence, precision, and required fields
        current_digits = _optional_integer(detail, "moneyDigits")
        if current_digits is None:
            raise ValueError("cTrader close-deal monetary precision is unavailable")
        if digits is not None and digits != current_digits:
            raise ValueError("cTrader close-deal monetary precision changed within one history window")
        digits = current_digits
        for field in ("grossProfit", "swap", "commission"):
            totals[{"grossProfit": "gross_profit", "swap": "swap", "commission": "commission"}[field]] += _required_integer(detail, field)
        fee = _optional_integer(detail, "pnlConversionFee")
        if fee is not None:
            totals["pnl_conversion_fee"] += fee
        close_count += 1

    if close_count == 0 or digits is None:
        return {
            "close_deals_count": 0,
            "money_digits": None,
            "gross_profit": None,
            "swap": None,
            "commission": None,
            "pnl_conversion_fee": None,
            "realized_net_pnl": None,
            "status": "no_closing_deals_in_window",
        }

    scale = 10 ** digits
    gross = totals["gross_profit"] / scale
    swap = totals["swap"] / scale
    commission = totals["commission"] / scale
    fee = totals["pnl_conversion_fee"] / scale
    return {
        "close_deals_count": close_count,
        "money_digits": digits,
        "gross_profit": gross,
        "swap": swap,
        "commission": commission,
        "pnl_conversion_fee": fee,
        "realized_net_pnl": gross + swap + commission + fee,
        "status": "broker_close_deal_components_summed",
    }


def _positive_timestamp(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer UTC timestamp in milliseconds")
    return value
