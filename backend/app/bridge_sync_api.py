from fastapi import APIRouter, Depends
from datetime import datetime, timezone
from .auth import current_user
from .db import connection

router=APIRouter(prefix="/v1/broker",tags=["broker-sync"])

@router.post("/pair")
def pair_bridge(body:dict|None=None,user=Depends(current_user)):
    body=body or {}
    bridge_id=str(body.get("bridge_id","windows-mt5")).strip()[:100] or "windows-mt5"
    with connection() as conn:
        conn.execute(
            """INSERT INTO bridge_pairings (bridge_id,user_id,updated_at)
               VALUES (%s,%s,now())
               ON CONFLICT (bridge_id) DO UPDATE SET user_id=EXCLUDED.user_id,updated_at=now()""",
            (bridge_id,user["id"])
        )
    return {"paired":True,"bridge_id":bridge_id,"user_id":user["id"]}

@router.get("/health")
def health(user=Depends(current_user)):
    with connection() as conn:
        row=conn.execute("SELECT payload,created_at FROM audit_events WHERE user_id=%s AND event_type='broker_connection' ORDER BY created_at DESC LIMIT 1",(user["id"],)).fetchone()
    if not row:
        return {"status":"disconnected","connected":False,"stale":True,"last_seen":None}
    payload=row[0] or {}
    age=max(0,(datetime.now(timezone.utc)-row[1]).total_seconds())
    stale=age>45
    status="stale" if stale else ("connected" if payload.get("connected") else "disconnected")
    return {"status":status,"connected":bool(payload.get("connected")) and not stale,"stale":stale,"last_seen":row[1],"age_seconds":round(age,1),"provider":payload.get("provider","MT5"),"environment":payload.get("environment","demo")}

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
