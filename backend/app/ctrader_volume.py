"""Strict validation of cTrader protocol order volumes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def validate_protocol_volume(volume: int, constraints: Mapping[str, Any]) -> int:
    """Validate a raw cTrader protocol volume against the broker's symbol limits.

    cTrader protocol volumes are integer values. The volume step is measured
    from the broker's minimum allowed volume, so validate the offset from min
    rather than assuming min_volume itself is divisible by step_volume.
    """
    if isinstance(volume, bool) or not isinstance(volume, int) or volume <= 0:
        raise RuntimeError("Order not sent: broker volume must be a positive protocol integer")

    try:
        minimum = int(constraints.get("min_volume") or 0)
        maximum = int(constraints.get("max_volume") or 0)
        step = int(constraints.get("step_volume") or 0)
    except (TypeError, ValueError, OverflowError):
        raise RuntimeError("Order not sent: cTrader returned invalid volume constraints") from None

    if minimum <= 0 or maximum < minimum or step <= 0:
        raise RuntimeError("Order not sent: cTrader returned incomplete volume constraints for this symbol")
    if volume < minimum or volume > maximum:
        raise RuntimeError(
            f"Order not sent: broker volume {volume} is outside the allowed range {minimum}–{maximum}"
        )
    if (volume - minimum) % step != 0:
        raise RuntimeError(
            f"Order not sent: broker volume {volume} does not match this symbol's minimum/step "
            f"({minimum} + n × {step})"
        )
    return volume
