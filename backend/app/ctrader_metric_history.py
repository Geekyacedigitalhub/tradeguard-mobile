"""Account-scoped cTrader demo equity history and conservative drawdown.

This module is deliberately not wired into trade approval yet. Callers must only
record values taken from a validated broker snapshot for the currently selected
demo account. Missing or invalid inputs are rejected, never coerced to zero.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from .db import connection
from .ctrader_snapshot_helpers import positive_integer


def _decimal_metric(value: Any, name: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{name} must be a finite non-negative number")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{name} must be a finite non-negative number") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ValueError(f"{name} must be a finite non-negative number")
    return parsed


def drawdown_percent_from_peak(peak_equity: Any, current_equity: Any) -> float | None:
    """Return peak-to-current percentage drawdown, or None for invalid inputs."""
    try:
        peak = _decimal_metric(peak_equity, "peak_equity")
        current = _decimal_metric(current_equity, "current_equity")
        if peak <= 0:
            return None
        result = max(Decimal("0"), (peak - current) / peak * Decimal("100"))
        value = float(result)
        return value if math.isfinite(value) and 0 <= value <= 100 else None
    except (ValueError, InvalidOperation, TypeError, OverflowError):
        return None


def record_demo_equity_snapshot(
    *,
    user_id: str,
    account_id: int,
    environment: str,
    balance: Any,
    equity: Any,
    currency: str,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    """Persist a validated demo snapshot and calculate peak-to-current drawdown.

    Drawdown is based on the highest persisted equity for this same account.
    It is unavailable when the current equity or history cannot be validated.
    """
    if isinstance(account_id, bool) or not isinstance(account_id, int) or account_id <= 0:
        raise ValueError("account_id must be a positive integer")
    if str(environment).strip().lower() != "demo":
        raise ValueError("Only cTrader demo snapshots can be recorded")
    if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError("currency must be a normalized three-letter code")
    balance_value = _decimal_metric(balance, "balance")
    equity_value = _decimal_metric(equity, "equity")
    instant = observed_at or datetime.now(timezone.utc)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("observed_at must be timezone-aware")
    instant = instant.astimezone(timezone.utc)

    with connection() as conn:
        selected = conn.execute(
            "SELECT account_id, environment FROM ctrader_connections WHERE user_id=%s",
            (user_id,),
        ).fetchone()
        if (
            not selected
            or positive_integer(selected[0]) != account_id
            or str(selected[1] or "demo").strip().lower() != "demo"
        ):
            raise ValueError("Snapshot does not match the currently selected demo account")

        conn.execute(
            """INSERT INTO ctrader_account_metric_history
               (user_id, account_id, environment, observed_at, balance, equity, currency, source)
               VALUES (%s, %s, 'demo', %s, %s, %s, %s, 'ctrader_broker_snapshot')
               ON CONFLICT (user_id, account_id, observed_at) DO NOTHING""",
            (user_id, account_id, instant, balance_value, equity_value, currency),
        )
        stored = conn.execute(
            """SELECT balance, equity, currency
               FROM ctrader_account_metric_history
               WHERE user_id=%s AND account_id=%s AND observed_at=%s
                 AND environment='demo'""",
            (user_id, account_id, instant),
        ).fetchone()
        if (
            not stored
            or Decimal(str(stored[0])) != balance_value
            or Decimal(str(stored[1])) != equity_value
            or stored[2] != currency
        ):
            raise ValueError("Conflicting snapshot already exists for this account timestamp")
        row = conn.execute(
            """SELECT MAX(equity), MIN(observed_at)
               FROM ctrader_account_metric_history
               WHERE user_id=%s AND account_id=%s AND environment='demo'
                 AND observed_at <= %s""",
            (user_id, account_id, instant),
        ).fetchone()

    peak = row[0] if row else None
    history_start = row[1].isoformat() if row and row[1] is not None else None
    if peak is None:
        return {
            "drawdown": None,
            "drawdown_status": "equity_peak_unavailable",
            "drawdown_verified": False,
            "peak_equity": None,
            "history_start": history_start,
            "observed_at": instant.isoformat(),
        }
    peak_value = _decimal_metric(peak, "peak_equity")
    drawdown_float = drawdown_percent_from_peak(peak_value, equity_value)
    if drawdown_float is None:
        return {
            "drawdown": None,
            "drawdown_status": "drawdown_calculation_unavailable",
            "drawdown_verified": False,
            "peak_equity": None,
            "history_start": history_start,
            "observed_at": instant.isoformat(),
        }

    # This table only knows observations since tracking was enabled. It
    # cannot prove the peak before the first stored snapshot, so this metric is
    # useful for diagnostics but must not be labeled verified lifetime drawdown.
    return {
        "drawdown": drawdown_float,
        "drawdown_status": "tracking_period_peak_only",
        "drawdown_verified": False,
        "peak_equity": float(peak_value),
        "history_start": history_start,
        "observed_at": instant.isoformat(),
    }
