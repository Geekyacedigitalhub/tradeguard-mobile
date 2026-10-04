from datetime import datetime, timezone
from .db import connection
import time

_ACCOUNT_CACHE={}
_ACCOUNT_CACHE_TTL=10

def live_account_metrics(user_id):
    cached=_ACCOUNT_CACHE.get(str(user_id))
    if cached and time.monotonic()-cached[0] < _ACCOUNT_CACHE_TTL:
        return dict(cached[1])
    """
    Return the freshest MT5 account metrics available to the backend.

    Falls back to account_state when the bridge heartbeat is older than 45s.
    Drawdown is measured from the highest MT5 equity heartbeat seen today.
    """
    with connection() as conn:
        state=conn.execute(
            "SELECT balance,equity,today_pl,drawdown,currency FROM account_state WHERE user_id=%s",
            (user_id,),
        ).fetchone()
        heartbeat=conn.execute(
            """SELECT payload,created_at
               FROM audit_events
               WHERE user_id=%s AND event_type='broker_connection'
               ORDER BY created_at DESC LIMIT 1""",
            (user_id,),
        ).fetchone()

    if not state:
        return None

    balance=float(state[0])
    equity=float(state[1])
    today_pl=float(state[2] or 0)
    drawdown=float(state[3] or 0)
    currency=state[4]

    if heartbeat:
        payload=heartbeat[0] or {}
        age=(datetime.now(timezone.utc)-heartbeat[1]).total_seconds()
        if payload.get("connected") and age <= 45:
            if payload.get("balance") is not None:
                balance=float(payload["balance"])
            if payload.get("equity") is not None:
                equity=float(payload["equity"])
            if payload.get("today_pl") is not None:
                today_pl=float(payload["today_pl"])

            # Use today's highest observed MT5 equity as the drawdown peak.
            with connection() as conn:
                peak_row=conn.execute(
                    """SELECT MAX((payload->>'equity')::double precision)
                       FROM audit_events
                       WHERE user_id=%s
                         AND event_type='broker_connection'
                         AND created_at >= CURRENT_DATE
                         AND (payload->>'connected')::boolean = true
                         AND payload->>'equity' IS NOT NULL""",
                    (user_id,),
                ).fetchone()
            peak_equity=float(peak_row[0]) if peak_row and peak_row[0] is not None else equity
            if peak_equity > 0:
                drawdown=max(0.0,(peak_equity-equity)/peak_equity*100)

            with connection() as conn:
                conn.execute(
                    """UPDATE account_state
                       SET balance=%s,equity=%s,today_pl=%s,drawdown=%s,updated_at=now()
                       WHERE user_id=%s""",
                    (balance,equity,today_pl,drawdown,user_id),
                )

    result={
        "balance":balance,
        "equity":equity,
        "today_pl":today_pl,
        "drawdown":drawdown,
        "currency":currency,
    }
    _ACCOUNT_CACHE[str(user_id)]=(time.monotonic(),result)
    return dict(result)
