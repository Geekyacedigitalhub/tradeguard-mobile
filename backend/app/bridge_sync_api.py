from fastapi import APIRouter, Depends
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
    return {
        "connected":bool(payload.get("connected",False)),
        "provider":payload.get("provider","MT5"),
        "environment":payload.get("environment","demo"),
        "account":payload.get("account"),
        "balance":payload.get("balance"),
        "equity":payload.get("equity"),
        "positions":payload.get("positions",[]),
        "updated_at":row[1],
    }
