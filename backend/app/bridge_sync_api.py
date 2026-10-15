from fastapi import APIRouter, Depends
from datetime import datetime, timezone
from .auth import current_user
from .db import connection

router=APIRouter(prefix="/v1/broker",tags=["broker-sync"])

_BROKER_HEALTH_CACHE={}
_BROKER_HEALTH_CACHE_TTL=5
_BROKER_SNAPSHOT_CACHE={}
_BROKER_SNAPSHOT_CACHE_TTL=5

@router.get("/health")
def health(user=Depends(current_user)):
    import time
    cache_key=str(user["id"])
    now=time.monotonic()
    cached=_BROKER_HEALTH_CACHE.get(cache_key)
    if cached and now-cached[0] < _BROKER_HEALTH_CACHE_TTL:
        return cached[1]
    with connection() as conn:
        row=conn.execute("SELECT payload,created_at FROM audit_events WHERE user_id=%s AND event_type='broker_connection' ORDER BY created_at DESC LIMIT 1",(user["id"],)).fetchone()
        # cTrader cloud must already have an authenticated heartbeat; never auto-pair a legacy terminal.
    if not row:
        result={"status":"disconnected","connected":False,"stale":True,"last_seen":None}
        _BROKER_HEALTH_CACHE[cache_key]=(now,result)
        return result
    payload=row[0] or {}
    age=max(0,(datetime.now(timezone.utc)-row[1]).total_seconds())
    stale=age>45
    status="stale" if stale else ("connected" if payload.get("connected") else "disconnected")
    result={"status":status,"connected":bool(payload.get("connected")) and not stale,"stale":stale,"last_seen":row[1],"age_seconds":round(age,1),"provider":payload.get("provider","cTrader Cloud"),"environment":payload.get("environment","demo")}
    _BROKER_HEALTH_CACHE[cache_key]=(now,result)
    return result

@router.get("/snapshot")
def snapshot(user=Depends(current_user)):
    import time
    cache_key=str(user["id"])
    now=time.monotonic()
    cached=_BROKER_SNAPSHOT_CACHE.get(cache_key)
    if cached and now-cached[0] < _BROKER_SNAPSHOT_CACHE_TTL:
        return cached[1]
    with connection() as conn:
        row=conn.execute(
            """SELECT payload,created_at
               FROM audit_events
               WHERE user_id=%s AND event_type='broker_connection'
               ORDER BY created_at DESC LIMIT 1""",
            (user["id"],)
        ).fetchone()
    if not row:
        result={"connected":False,"provider":"none","environment":"paper","account":None,"balance":None,"equity":None,"positions":[]}
        _BROKER_SNAPSHOT_CACHE[cache_key]=(now,result)
        return result
    payload=row[0] or {}
    updated_at=row[1]
    age_seconds=max(0,(datetime.now(timezone.utc)-updated_at).total_seconds())
    stale=age_seconds>45
    result={
        "connected":bool(payload.get("connected",False)) and not stale,
        "stale":stale,
        "age_seconds":round(age_seconds,1),
        "provider":payload.get("provider","cTrader Cloud"),
        "environment":payload.get("environment","demo"),
        "account":payload.get("account"),
        "balance":payload.get("balance"),
        "equity":payload.get("equity"),
        "positions":payload.get("positions",[]) if not stale else [],
        "updated_at":updated_at,
    }
    _BROKER_SNAPSHOT_CACHE[cache_key]=(now,result)
    return result
