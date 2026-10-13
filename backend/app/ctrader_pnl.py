import math


def calculate_realized_pnl(deals, *, has_more=False, default_money_digits=2):
    """Return complete realized P/L in account currency, or None for truncated history.

    cTrader monetary integer fields are scaled by moneyDigits. Commission and
    swap are applied with the signs supplied by the broker; conversion fees
    are costs and are subtracted. Malformed monetary data is rejected instead
    of leaking NaN or infinity into account risk metrics.
    """
    if has_more:
        return None
    realized = 0.0
    for deal in deals or []:
        detail = getattr(deal, "closePositionDetail", None)
        if detail is None:
            continue
        raw_digits = getattr(detail, "moneyDigits", getattr(deal, "moneyDigits", default_money_digits))
        if raw_digits is None:
            raw_digits = default_money_digits
        if isinstance(raw_digits, bool) or not isinstance(raw_digits, int) or raw_digits < 0 or raw_digits > 12:
            raise ValueError("Invalid cTrader moneyDigits")
        scale = 10 ** raw_digits
        components = (
            getattr(detail, "grossProfit", 0),
            getattr(detail, "swap", 0),
            getattr(detail, "commission", 0),
            getattr(detail, "pnlConversionFee", 0),
        )
        values = []
        for component in components:
            if isinstance(component, bool):
                raise ValueError("Invalid cTrader monetary value")
            try:
                value = float(component or 0)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError("Invalid cTrader monetary value") from exc
            if not math.isfinite(value):
                raise ValueError("Invalid cTrader monetary value")
            values.append(value)
        gross, swap, commission, conversion_fee = values
        realized += (gross + swap + commission - conversion_fee) / scale
        if not math.isfinite(realized):
            raise ValueError("Invalid cTrader realized P/L total")
    return realized



def calculate_unrealized_pnl_by_position(rows, *, money_digits):
    """Map broker-reported unrealized P/L to position IDs without inventing values.

    Rows without a valid positive position ID are ignored for the per-position
    map; callers can still display the separately calculated account total.
    """
    if isinstance(money_digits, bool) or not isinstance(money_digits, int) or not 0 <= money_digits <= 12:
        raise ValueError("Invalid cTrader moneyDigits")
    scale = 10 ** money_digits
    result = {}
    for row in rows or []:
        position_id = getattr(row, "positionId", None)
        if isinstance(position_id, bool) or not isinstance(position_id, int) or position_id <= 0:
            continue
        raw = getattr(row, "netUnrealizedPnL", None)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise ValueError("Invalid cTrader unrealized P/L value")
        value = float(raw) / scale
        if not math.isfinite(value):
            raise ValueError("Invalid cTrader unrealized P/L value")
        result[position_id] = value
    return result



def calculate_unrealized_pnl_snapshot(rows, *, expected_position_ids, money_digits):
    """Validate and total a complete broker P/L snapshot against open positions.

    A snapshot is rejected when rows are duplicated, malformed, or do not
    correspond exactly to the reconciled open-position set. This prevents the
    account equity total and per-position P/L display from disagreeing.
    """
    expected = set()
    for value in expected_position_ids:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError("Invalid reconciled cTrader position ID")
        if value in expected:
            raise ValueError("Duplicate reconciled cTrader position ID")
        expected.add(value)

    result = {}
    for row in rows or []:
        position_id = getattr(row, "positionId", None)
        if isinstance(position_id, bool) or not isinstance(position_id, int) or position_id <= 0:
            raise ValueError("Invalid cTrader unrealized P/L position ID")
        if position_id in result:
            raise ValueError("Duplicate cTrader unrealized P/L position ID")
        result[position_id] = row

    actual = set(result)
    if actual != expected:
        raise ValueError("cTrader unrealized P/L rows do not match reconciled open positions")

    mapped = calculate_unrealized_pnl_by_position(list(result.values()), money_digits=money_digits)
    total = math.fsum(mapped.values())
    if not math.isfinite(total):
        raise ValueError("Invalid cTrader unrealized P/L total")
    return mapped, total
