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
