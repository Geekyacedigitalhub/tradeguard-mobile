import json
import os
from uuid import UUID
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from .db import connection

router=APIRouter(prefix="/v1/bridge",tags=["mt5-bridge"])
BRIDGE_SECRET=os.getenv("MT5_BRIDGE_SECRET")

def require_bridge(secret,user_id):
    if not BRIDGE_SECRET or not secret or secret != BRIDGE_SECRET:
        raise HTTPException(401,"Invalid bridge credentials")
    try:
        return str(UUID(user_id))
    except (ValueError,TypeError):
        raise HTTPException(400,"Invalid bridge user id")

class Heartbeat(BaseModel):
    user_id:str
    account:str|None=None
    environment:str="demo"
    terminal:str="MT5"
    connected:bool=False
    balance:float|None=None
    equity:float|None=None
    positions:list[dict]=[]

class MarketData(BaseModel):
    user_id:str
    symbol:str
    timeframe:str="15m"
    candles:list[dict]=[]

class CommandResult(BaseModel):
    command_id:int
    status:str
    result:dict={}

@router.post("/heartbeat")
def heartbeat(body:Heartbeat,x_bridge_secret:str|None=Header(default=None)):
    user_id=require_bridge(x_bridge_secret,body.user_id)
    payload={"connected":body.connected,"provider":"MT5","environment":body.environment,"account":body.account,"terminal":body.terminal,"balance":body.balance,"equity":body.equity,"positions":body.positions}
    with connection() as conn:
        conn.execute("INSERT INTO audit_events (user_id,event_type,payload) VALUES (%s,'broker_connection',%s::jsonb)",(user_id,json.dumps(payload)))
    return {"ok":True,**payload}

@router.post("/market-data")
def market_data(body:MarketData,x_bridge_secret:str|None=Header(default=None)):
    user_id=require_bridge(x_bridge_secret,body.user_id)
    if body.timeframe not in ("15m",):
        raise HTTPException(400,"Unsupported timeframe")
    candles=body.candles[-200:]
    if not candles:
        raise HTTPException(400,"No candles supplied")
    with connection() as conn:
        conn.execute("""INSERT INTO bridge_market_data (user_id,symbol,timeframe,candles,updated_at)
                        VALUES (%s,%s,%s,%s::jsonb,now())
                        ON CONFLICT (user_id,symbol,timeframe) DO UPDATE SET candles=EXCLUDED.candles,updated_at=now()""",
                     (user_id,body.symbol.upper(),body.timeframe,json.dumps(candles)))
    return {"ok":True,"symbol":body.symbol.upper(),"timeframe":body.timeframe,"count":len(candles)}

@router.get("/commands")
def commands(x_bridge_secret:str|None=Header(default=None),x_bridge_user:str|None=Header(default=None),limit:int=10):
    user_id=require_bridge(x_bridge_secret,x_bridge_user)
    limit=max(1,min(limit,50))
    with connection() as conn:
        rows=conn.execute("""SELECT id,user_id,command_type,payload,created_at FROM bridge_commands WHERE status='pending' AND user_id=%s ORDER BY id LIMIT %s""",(user_id,limit)).fetchall()
        ids=[r[0] for r in rows]
        if ids:
            conn.execute("UPDATE bridge_commands SET status='claimed',claimed_at=now() WHERE id = ANY(%s) AND user_id=%s",(ids,user_id))
    return {"commands":[{"id":r[0],"user_id":str(r[1]),"type":r[2],"payload":r[3],"created_at":r[4]} for r in rows]}

@router.post("/commands/result")
def command_result(body:CommandResult,x_bridge_secret:str|None=Header(default=None),x_bridge_user:str|None=Header(default=None)):
    user_id=require_bridge(x_bridge_secret,x_bridge_user)
    if body.status not in ("completed","failed"):
        raise HTTPException(400,"Status must be completed or failed")
    with connection() as conn:
        updated=conn.execute("""UPDATE bridge_commands SET status=%s,completed_at=now(),result=%s::jsonb WHERE id=%s AND user_id=%s AND status='claimed' RETURNING id""",(body.status,json.dumps(body.result),body.command_id,user_id)).fetchone()
    if not updated:
        raise HTTPException(404,"Bridge command not found or already completed")
    return {"ok":True,"command_id":body.command_id,"status":body.status}
