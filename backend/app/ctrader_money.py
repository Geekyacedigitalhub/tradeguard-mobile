import math


def validate_money_digits(value, *, fallback=None):
    """Validate cTrader monetary precision before scaling protocol values."""
    if value is None:
        value = fallback
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 12:
        raise ValueError("Invalid cTrader moneyDigits")
    return value


def decode_money_value(value, money_digits, *, field="monetary value"):
    """Decode a cTrader integer money field and reject malformed/non-finite data."""
    digits = validate_money_digits(money_digits)
    if isinstance(value, bool):
        raise ValueError(f"Invalid cTrader {field}")
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"Invalid cTrader {field}") from exc
    if not math.isfinite(numeric):
        raise ValueError(f"Invalid cTrader {field}")
    decoded = numeric / (10 ** digits)
    if not math.isfinite(decoded):
        raise ValueError(f"Invalid cTrader {field}")
    return decoded



def decode_ctrader_equity_snapshot(trader, pnl_response):
    """Return broker balance/equity only when every required money field is valid."""
    if trader is None or pnl_response is None:
        raise ValueError("Missing cTrader equity snapshot")

    balance_digits = validate_money_digits(getattr(trader, "moneyDigits", None))
    balance = decode_money_value(
        getattr(trader, "balance", None),
        balance_digits,
        field="balance",
    )
    pnl_digits = validate_money_digits(
        getattr(pnl_response, "moneyDigits", None),
        fallback=balance_digits,
    )
    positions = getattr(pnl_response, "positionUnrealizedPnL", None)
    if not isinstance(positions, (list, tuple)):
        raise ValueError("Invalid cTrader unrealized P/L positions")

    unrealized = 0.0
    for position in positions:
        if position is None:
            raise ValueError("Invalid cTrader unrealized P/L position")
        unrealized += decode_money_value(
            getattr(position, "netUnrealizedPnL", None),
            pnl_digits,
            field="unrealized P/L",
        )
        if not math.isfinite(unrealized):
            raise ValueError("Invalid cTrader unrealized P/L total")

    equity = balance + unrealized
    if not math.isfinite(equity):
        raise ValueError("Invalid cTrader equity")
    return balance, equity
