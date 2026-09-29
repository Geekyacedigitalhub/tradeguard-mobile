from fastapi import APIRouter, Depends
from datetime import datetime, timezone
from .auth import current_user
from .db import connection

router=APIRouter(prefix="/v1/broker",tags=["broker-sync"])

@router.get("/snapshot")
def snapshot(user=Depends(current_user)):
    with connection() as conn:
        row=conn.execute(
            """SELECT payload,created_at
               FROM audit_events
               WHERE user_id=%s AND event_type='broker_connection'
               ORDER BY created_at DESC LIMIT 1""",
            (user["id"],)
        ).fetchone()
    if not row:
        return {"connected":False,"provider":"none","environment":"paper","account":None,"balance":None,"equity":None,"positions":[]}
    payload=row[0] or {}
    updated_at=row[1]
    age_seconds=max(0,(datetime.now(timezone.utc)-updated_at).total_seconds())
    stale=age_seconds>45
    return {
        "connected":bool(payload.get("connected",False)) and not stale,
        "stale":stale,
        "age_seconds":round(age_seconds,1),
        "provider":payload.get("provider","MT5"),
        "environment":payload.get("environment","demo"),
        "account":payload.get("account"),
        "balance":payload.get("balance"),
        "equity":payload.get("equity"),
        "positions":payload.get("positions",[]) if not stale else [],
        "updated_at":updated_at,
    }
