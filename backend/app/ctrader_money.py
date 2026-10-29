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
    # cTrader monetary protocol fields are numeric values. Do not coerce
    # strings or arbitrary objects: accepting them can hide malformed broker
    # payloads and turn display data into apparent financial truth.
    # cTrader protobuf monetary fields are integer-scaled values. Accepting
    # floats (even finite ones) would silently tolerate a schema mismatch.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Invalid cTrader {field}")
    # Integer protocol amounts above IEEE-754's exact-integer range lose
    # precision when converted to float. Fail closed rather than display or
    # use a rounded broker balance/P&L as financial truth.
    if isinstance(value, int) and abs(value) > (1 << 53):
        raise ValueError(f"Invalid cTrader {field}")
    decoded = value / (10 ** digits)
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
        # Include what we actually received: when the broker serves a
        # malformed P/L response (wedged account session), the /diag/status
        # error log must show the shape, not just "invalid".
        shape = f"pnl_response type={type(pnl_response).__name__}, positions={positions!r}"
        if isinstance(pnl_response, dict):
            shape += f", keys={sorted(pnl_response.keys())!r}"
        else:
            try:
                fields = {f.name: getattr(pnl_response, f.name, None) for f in pnl_response.DESCRIPTOR.fields}
                shape += f", fields={ {k: repr(v)[:40] for k, v in fields.items()}!r}"
            except Exception:
                shape += f", attrs={ [a for a in dir(pnl_response) if not a.startswith('_')][:12]!r}"
        raise ValueError(f"Invalid cTrader unrealized P/L positions ({shape})")

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
