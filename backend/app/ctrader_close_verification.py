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
    if after_volume > before_volume:
        return "changed_unexpectedly"
    if after_volume == before_volume:
        return "unconfirmed"
    if before_volume - after_volume == requested_volume:
        return "confirmed_reduced"
    return "changed_unexpectedly"

def _confirmed_close_result(result: dict) -> bool:
    """Require internally consistent broker before/after volume evidence."""
    if not isinstance(result, dict):
        return False
    status = result.get("status")
    before = result.get("volume_before")
    requested = result.get("requested_close_volume")
    after = result.get("volume_after")
    if (
        isinstance(before, bool) or not isinstance(before, int) or before <= 0
        or isinstance(requested, bool) or not isinstance(requested, int) or requested <= 0
        or requested > before or "volume_after" not in result
    ):
        return False
    if status == "confirmed_closed":
        return requested == before and after is None
    if status == "confirmed_reduced":
        return (
            isinstance(after, int) and not isinstance(after, bool) and after > 0
            and before - after == requested
        )
    return False


def broker_outcome_is_confirmed(command_type: str, command_status: str, result: dict) -> bool:
    """Return true only when a completed command includes evidence for its claimed outcome."""
    if command_status != "completed" or not isinstance(result, dict):
        return False
    status = result.get("status")
    if command_type == "close_position":
        return _confirmed_close_result(result)
    if command_type == "close_all_positions":
        positions = result.get("positions")
        attempted = result.get("attempted_count")
        closed = result.get("confirmed_closed_count")
        if status == "no_open_positions":
            return (
                isinstance(attempted, int) and not isinstance(attempted, bool) and attempted == 0
                and isinstance(closed, int) and not isinstance(closed, bool) and closed == 0
                and positions == []
            )
        return (
            status == "confirmed_closed"
            and isinstance(attempted, int) and not isinstance(attempted, bool) and attempted > 0
            and isinstance(closed, int) and not isinstance(closed, bool) and closed == attempted
            and isinstance(positions, list) and len(positions) == attempted
            and all(_confirmed_close_result(position) and position.get("status") == "confirmed_closed" for position in positions)
        )
    if command_type == "protect_position" and status == "confirmed_protected":
        try:
            return classify_protection_result(
                result.get("protection_before"),
                result.get("requested_stop_loss"),
                result.get("requested_take_profit"),
                result.get("protection_after"),
            ) == "confirmed_protected"
        except (TypeError, ValueError):
            return False
    return False


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
            return actual is None
        if isinstance(actual, bool) or not isinstance(actual, (int, float)):
            return False
        actual_value = float(actual)
        return math.isfinite(actual_value) and math.isclose(actual_value, float(expected), rel_tol=0.0, abs_tol=1e-9)

    # An omitted field means "leave unchanged", not "ignore verification".
    # Compare it with the pre-amendment broker snapshot so an amendment that
    # accidentally removes the other protection is never reported as confirmed.
    expected_stop_loss = requested_stop_loss if requested_stop_loss is not None else before.get("stop_loss")
    expected_take_profit = requested_take_profit if requested_take_profit is not None else before.get("take_profit")
    if not matches(after.get("stop_loss"), expected_stop_loss):
        return "stop_loss_unconfirmed"
    if not matches(after.get("take_profit"), expected_take_profit):
        return "take_profit_unconfirmed"
    return "confirmed_protected"

