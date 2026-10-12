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
