MAX_PROTOCOL_VOLUME = (1 << 63) - 1


def validate_protocol_volume(value, *, field="volume"):
    """Require a positive integer cTrader protocol volume without coercion."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0 or value > MAX_PROTOCOL_VOLUME:
        raise ValueError(f"cTrader {field} must be a positive broker protocol integer")
    return value


def validate_symbol_volume_metadata(min_volume, max_volume, step_volume):
    """Validate raw broker volume limits without silently coercing bad metadata."""
    values = {
        "minimum volume": min_volume,
        "maximum volume": max_volume,
        "volume step": step_volume,
    }
    for field, value in values.items():
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0 or value > MAX_PROTOCOL_VOLUME:
            raise ValueError(f"cTrader symbol {field} must be a positive broker protocol integer")
    if max_volume < min_volume:
        raise ValueError("cTrader symbol maximum volume cannot be below minimum volume")
    return min_volume, max_volume, step_volume
