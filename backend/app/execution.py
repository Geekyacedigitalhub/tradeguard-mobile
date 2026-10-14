from datetime import datetime, timezone
from .db import connection

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
    # cTrader heartbeat snapshots create a fresh audit event every 10 seconds;
    # account_state.updated_at belongs to the retired EA flow and can be stale.
    last_seen=row[1]
    age=max(0.0,(datetime.now(timezone.utc)-last_seen).total_seconds())
    terminal=str(payload.get("terminal") or "")
    provider=CLOUD_EXECUTION_TERMINALS.get(terminal,"none")
    connected=bool(payload.get("connected")) and age<=45 and provider!="none"
    return {
        "connected":connected,
        "provider":provider,
        "terminal":terminal,
        "environment":payload.get("environment"),
        "account":payload.get("account"),
        "payload":payload,
        "positions":payload.get("positions") if isinstance(payload.get("positions"),list) else [],
        "last_seen":last_seen,
        "age_seconds":round(age,1),
    }

def execution_connected(user_id):
    return bool(execution_snapshot(user_id)["connected"])

def execution_provider(user_id):
    snap=execution_snapshot(user_id)
    return snap["provider"] if snap["connected"] else "none"
