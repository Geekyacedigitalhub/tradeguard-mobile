from __future__ import annotations


def position_volume_snapshot(reconcile_response, position_id: int) -> int | None:
    """Return broker-reported raw volume for a position, or None if absent."""
    matches = []
    for position in getattr(reconcile_response, "position", []):
        current_id = getattr(position, "positionId", None)
        if isinstance(current_id, bool) or not isinstance(current_id, int):
            continue
        if current_id != position_id:
            continue
        trade_data = getattr(position, "tradeData", None)
        volume = getattr(trade_data, "volume", None)
        if isinstance(volume, bool) or not isinstance(volume, int) or volume <= 0:
            raise ValueError("cTrader returned invalid volume for the selected position")
        matches.append(volume)
    if len(matches) > 1:
        raise ValueError("cTrader reconcile returned duplicate entries for the selected position")
    return matches[0] if matches else None


def classify_close_result(before_volume: int, requested_volume: int, after_volume: int | None) -> str:
    """Classify close outcome only from broker-reconciled before/after position state."""
    for label, value in (("before volume", before_volume), ("requested volume", requested_volume)):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"cTrader {label} must be a positive integer")
    if requested_volume > before_volume:
        raise ValueError("Requested close volume exceeds broker-reported position volume")
    if after_volume is None:
        return "confirmed_closed"
    if isinstance(after_volume, bool) or not isinstance(after_volume, int) or after_volume <= 0:
        raise ValueError("cTrader returned invalid post-close position volume")
    if after_volume >= before_volume:
        return "unconfirmed"
    if before_volume - after_volume == requested_volume:
        return "confirmed_reduced"
    return "changed_unexpectedly"
