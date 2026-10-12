from datetime import datetime, timezone

from .db import connection

# TradeGuard currently permits automated execution only through its cloud
# cTrader Demo account. Legacy MT5 heartbeat rows must never select a broker.
CLOUD_EXECUTION_TERMINALS={"cTrader Cloud":"ctrader"}


def execution_snapshot(user_id):
    with connection() as conn:
        row=conn.execute(
            """SELECT ae.payload,ae.created_at,ast.updated_at
                 FROM audit_events ae
                 LEFT JOIN account_state ast ON ast.user_id=ae.user_id
                WHERE ae.user_id=%s AND ae.event_type='broker_connection'
                ORDER BY ae.created_at DESC LIMIT 1""",
            (user_id,),
        ).fetchone()
    if not row:
        return {"connected":False,"provider":"none","terminal":None,"payload":{},"positions":[],"age_seconds":None}
    payload=row[0] or {}
    last_seen=row[1]
    if last_seen.tzinfo is None:
        last_seen=last_seen.replace(tzinfo=timezone.utc)
    age=max(0.0,(datetime.now(timezone.utc)-last_seen).total_seconds())
    terminal=str(payload.get("terminal") or "")
    provider=CLOUD_EXECUTION_TERMINALS.get(terminal,"none")
    environment=str(payload.get("environment") or "").lower()
    connected=bool(payload.get("connected")) and age<=45 and provider=="ctrader" and environment in ("demo","live")
    return {
        "connected":connected,
        "provider":provider if connected else "none",
        "terminal":terminal,
        "environment":environment or None,
        "account":payload.get("account"),
        "payload":payload,
        "positions":payload.get("positions") if isinstance(payload.get("positions"),list) else [],
        "last_seen":last_seen,
        "age_seconds":round(age,1),
        "automated_execution_allowed":connected and environment=="demo",
    }


def execution_connected(user_id):
    return bool(execution_snapshot(user_id)["connected"])


def execution_provider(user_id):
    snapshot=execution_snapshot(user_id)
    return snapshot["provider"] if snapshot["connected"] else "none"
