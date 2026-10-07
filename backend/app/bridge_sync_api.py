from fastapi import APIRouter, Depends
from datetime import datetime, timezone
import hashlib
import secrets
from .auth import current_user
from .db import connection
from .bridge_api import _BRIDGE_IDENTITY_CACHE

router=APIRouter(prefix="/v1/broker",tags=["broker-sync"])
_BROKER_HEALTH_CACHE={}
_BROKER_HEALTH_CACHE_TTL=5
_BROKER_SNAPSHOT_CACHE={}
_BROKER_SNAPSHOT_CACHE_TTL=5

@router.post("/ea-pair-code")
def create_ea_pair_code(user=Depends(current_user)):
    bridge_id="cloud-mt5-ea"
    code=f"{secrets.randbelow(100000000):08d}"
    code_hash=hashlib.sha256(code.encode("utf-8")).hexdigest()
    with connection() as conn:
        conn.execute(
            """INSERT INTO bridge_pairings (bridge_id,user_id,updated_at)
               VALUES (%s,%s,now())
               ON CONFLICT (bridge_id) DO UPDATE SET user_id=EXCLUDED.user_id,updated_at=now()""",
            (bridge_id,user["id"])
        )
        conn.execute(
            """INSERT INTO bridge_pairing_codes (bridge_id,user_id,code_hash,expires_at,used_at,created_at)
               VALUES (%s,%s,%s,now()+interval '5 minutes',NULL,now())
               ON CONFLICT (bridge_id) DO UPDATE
               SET user_id=EXCLUDED.user_id,code_hash=EXCLUDED.code_hash,expires_at=EXCLUDED.expires_at,used_at=NULL,created_at=now()""",
            (bridge_id,user["id"],code_hash)
        )
    return {"bridge_id":bridge_id,"code":code,"expires_in_seconds":300}

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
    _BRIDGE_IDENTITY_CACHE.pop(bridge_id,None)
    _BROKER_HEALTH_CACHE.pop(str(user["id"]),None)
    _BROKER_SNAPSHOT_CACHE.pop(str(user["id"]),None)
    return {"paired":True,"bridge_id":bridge_id,"user_id":user["id"]}

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
        if not row:
            candidates=conn.execute(
                """SELECT user_id,payload,created_at
                   FROM audit_events
                   WHERE event_type='broker_connection'
                     AND created_at >= now() - interval '45 seconds'
                     AND COALESCE((payload->>'connected')::boolean,false)=true
                   ORDER BY created_at DESC LIMIT 10"""
            ).fetchall()
            user_ids={str(r[0]) for r in candidates}
            if len(user_ids)==1 and candidates:
                conn.execute(
                    """INSERT INTO bridge_pairings (bridge_id,user_id,updated_at)
                       VALUES ('windows-mt5',%s,now())
                       ON CONFLICT (bridge_id) DO UPDATE SET user_id=EXCLUDED.user_id,updated_at=now()""",
                    (user["id"],)
                )
                row=(candidates[0][1],candidates[0][2])
    if not row:
        result={"status":"disconnected","connected":False,"stale":True,"last_seen":None}
        _BROKER_HEALTH_CACHE[cache_key]=(now,result)
        return result
    payload=row[0] or {}
    age=max(0,(datetime.now(timezone.utc)-row[1]).total_seconds())
    stale=age>45
    status="stale" if stale else ("connected" if payload.get("connected") else "disconnected")
    result={"status":status,"connected":bool(payload.get("connected")) and not stale,"stale":stale,"last_seen":row[1],"age_seconds":round(age,1),"provider":payload.get("provider","MT5"),"environment":payload.get("environment","demo")}
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
        "provider":payload.get("provider","MT5"),
        "environment":payload.get("environment","demo"),
        "account":payload.get("account"),
        "balance":payload.get("balance"),
        "equity":payload.get("equity"),
        "positions":payload.get("positions",[]) if not stale else [],
        "updated_at":updated_at,
    }
    _BROKER_SNAPSHOT_CACHE[cache_key]=(now,result)
    return result
