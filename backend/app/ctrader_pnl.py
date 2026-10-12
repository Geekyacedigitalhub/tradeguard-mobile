def calculate_realized_pnl(deals, *, has_more=False, default_money_digits=2):
    """Return complete realized P/L in account currency, or None for truncated history.

    cTrader monetary integer fields are scaled by moneyDigits. Commission and
    swap are applied with the signs supplied by the broker; conversion fees
    are costs and are subtracted.
    """
    if has_more:
        return None
    realized = 0.0
    for deal in deals or []:
        detail = getattr(deal, "closePositionDetail", None)
        if detail is None:
            continue
        digits = int(
            getattr(detail, "moneyDigits", getattr(deal, "moneyDigits", default_money_digits))
            or 0
        )
        if digits < 0 or digits > 12:
            raise ValueError("Invalid cTrader moneyDigits")
        scale = 10 ** digits
        realized += (
            float(getattr(detail, "grossProfit", 0) or 0)
            + float(getattr(detail, "swap", 0) or 0)
            + float(getattr(detail, "commission", 0) or 0)
            - float(getattr(detail, "pnlConversionFee", 0) or 0)
        ) / scale
    return realized
