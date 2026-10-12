def validate_protocol_volume(value, *, field="volume"):
    """Require a positive integer cTrader protocol volume without coercion."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"cTrader {field} must be a positive broker protocol integer")
    return value
