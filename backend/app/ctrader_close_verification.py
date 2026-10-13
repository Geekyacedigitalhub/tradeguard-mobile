from __future__ import annotations

import math


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
        # A disappeared position confirms a full close only when the requested
        # volume covered the entire broker-reported position. If a partial close
        # was requested, disappearance is an unexpected broker-state change.
        return "confirmed_closed" if requested_volume == before_volume else "changed_unexpectedly"
    if isinstance(after_volume, bool) or not isinstance(after_volume, int) or after_volume <= 0:
        raise ValueError("cTrader returned invalid post-close position volume")
    if after_volume >= before_volume:
        return "unconfirmed"
    if before_volume - after_volume == requested_volume:
        return "confirmed_reduced"
    return "changed_unexpectedly"

def protection_snapshot(reconcile_response, position_id: int) -> dict | None:
    """Return broker-reported SL/TP values for one position, preserving absent fields."""
    matches = []
    for position in getattr(reconcile_response, "position", []):
        current_id = getattr(position, "positionId", None)
        if isinstance(current_id, bool) or not isinstance(current_id, int):
            continue
        if current_id != position_id:
            continue
        matches.append({
            "stop_loss": getattr(position, "stopLoss", None),
            "take_profit": getattr(position, "takeProfit", None),
        })
    if len(matches) > 1:
        raise ValueError("cTrader reconcile returned duplicate entries for the selected position")
    return matches[0] if matches else None


def classify_protection_result(
    before: dict | None,
    requested_stop_loss: float | None,
    requested_take_profit: float | None,
    after: dict | None,
) -> str:
    """Confirm requested protection values only from broker-reconciled position state."""
    if before is None:
        raise ValueError("cTrader protection verification requires a broker-confirmed position before amendment")
    if after is None:
        return "position_missing_after_amendment"
    if requested_stop_loss is None and requested_take_profit is None:
        raise ValueError("At least one stop loss or take profit value is required")

    def matches(actual, expected):
        if expected is None:
            return True
        if isinstance(actual, bool) or not isinstance(actual, (int, float)):
            return False
        actual_value = float(actual)
        return math.isfinite(actual_value) and math.isclose(actual_value, float(expected), rel_tol=0.0, abs_tol=1e-9)

    if not matches(after.get("stop_loss"), requested_stop_loss):
        return "stop_loss_unconfirmed"
    if not matches(after.get("take_profit"), requested_take_profit):
        return "take_profit_unconfirmed"
    return "confirmed_protected"

