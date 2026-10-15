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


def normalize_close_deal(deal: Any) -> dict[str, int | float | None]:
    """Return validated scaled components for a broker-reported closing deal.

    This does not aggregate P/L. A closePositionDetail is only present on
    closing deals, and moneyDigits is required to interpret its integer amounts.
    """
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
