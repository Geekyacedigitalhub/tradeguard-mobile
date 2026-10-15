from datetime import datetime, timezone
import math
import re
import time
from .db import connection

_ACCOUNT_CACHE={}
_ACCOUNT_CACHE_TTL=10


def live_account_metrics(user_id):
    """Return only fresh, verified cTrader demo metrics; never reuse legacy terminal state."""
    key=str(user_id)
    cached=_ACCOUNT_CACHE.get(key)
    if cached and time.monotonic()-cached[0] < _ACCOUNT_CACHE_TTL:
        return dict(cached[1]) if cached[1] is not None else None

    with connection() as conn:
        selected=conn.execute(
            "SELECT account_id,environment FROM ctrader_connections WHERE user_id=%s",
            (user_id,),
        ).fetchone()
        heartbeat=conn.execute(
            """SELECT payload,created_at
               FROM audit_events
               WHERE user_id=%s AND event_type='broker_connection'
               ORDER BY created_at DESC LIMIT 1""",
            (user_id,),
        ).fetchone()

    if not selected or not selected[0] or str(selected[1] or "demo").lower() != "demo" or not heartbeat:
        _ACCOUNT_CACHE[key]=(time.monotonic(),None)
        return None

    payload=heartbeat[0]
    if not isinstance(payload,dict):
        _ACCOUNT_CACHE[key]=(time.monotonic(),None)
        return None
    age=(datetime.now(timezone.utc)-heartbeat[1]).total_seconds()
    if (
        not payload.get("connected")
        or payload.get("terminal") != "cTrader Cloud"
        or payload.get("provider") != "cTrader"
        or str(payload.get("environment") or "demo").lower() != "demo"
        or str(payload.get("account")) != str(selected[0])
        or age < 0
        or age > 45
    ):
        _ACCOUNT_CACHE[key]=(time.monotonic(),None)
        return None

    # A connection heartbeat currently proves account connectivity, not balance,
    # equity, daily P/L, or drawdown. Do not substitute stale account_state values.
    fields=("balance","equity","today_pl","drawdown")
    metrics={}
    for field in fields:
        value=payload.get(field)
        if isinstance(value,bool) or value is None:
            _ACCOUNT_CACHE[key]=(time.monotonic(),None)
            return None
        try:
            value=float(value)
        except (TypeError,ValueError,OverflowError):
            _ACCOUNT_CACHE[key]=(time.monotonic(),None)
            return None
        if not math.isfinite(value):
            _ACCOUNT_CACHE[key]=(time.monotonic(),None)
            return None
        if (field in ("balance","equity") and value < 0) or (field == "drawdown" and not 0 <= value <= 100):
            _ACCOUNT_CACHE[key]=(time.monotonic(),None)
            return None
        metrics[field]=value

    currency=payload.get("currency")
    if not isinstance(currency,str) or not re.fullmatch(r"[A-Z]{3}",currency.strip()):
        _ACCOUNT_CACHE[key]=(time.monotonic(),None)
        return None
    metrics["currency"]=currency.strip()
    _ACCOUNT_CACHE[key]=(time.monotonic(),metrics)
    return dict(metrics)
