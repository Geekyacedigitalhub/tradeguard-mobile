import json
import os
from uuid import UUID
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from .db import connection
from .notifications_api import notification_event, send_push

router=APIRouter(prefix="/v1/bridge",tags=["mt5-bridge"])
BRIDGE_SECRET=os.getenv("MT5_BRIDGE_SECRET")

def require_bridge(secret,user_id):
    if not BRIDGE_SECRET or not secret or secret != BRIDGE_SECRET:
        raise HTTPException(401,"Invalid bridge credentials")
    with connection() as conn:
        row=conn.execute("SELECT user_id FROM bridge_pairings WHERE bridge_id='windows-mt5' LIMIT 1").fetchone()
    if row:
        return str(row[0])
    if not user_id:
        raise HTTPException(400,"Bridge user id is required")
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
    today_pl:float|None=None
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

@router.get("/pairing")
def pairing(bridge_id:str="windows-mt5",x_bridge_secret:str|None=Header(default=None)):
    if not BRIDGE_SECRET or not x_bridge_secret or x_bridge_secret != BRIDGE_SECRET:
        raise HTTPException(401,"Invalid bridge credentials")
    bridge_id=(bridge_id or "windows-mt5").strip()[:100]
    with connection() as conn:
        row=conn.execute("SELECT user_id,updated_at FROM bridge_pairings WHERE bridge_id=%s",(bridge_id,)).fetchone()
    if not row:
        return {"paired":False,"bridge_id":bridge_id,"user_id":None}
    return {"paired":True,"bridge_id":bridge_id,"user_id":str(row[0]),"updated_at":row[1]}

@router.post("/heartbeat")
def heartbeat(body:Heartbeat,x_bridge_secret:str|None=Header(default=None)):
    user_id=require_bridge(x_bridge_secret,body.user_id)
    payload={"connected":body.connected,"provider":"MT5","environment":body.environment,"account":body.account,"terminal":body.terminal,"balance":body.balance,"equity":body.equity,"today_pl":body.today_pl,"positions":body.positions}
    with connection() as conn:
        conn.execute("INSERT INTO audit_events (user_id,event_type,payload) VALUES (%s,'broker_connection',%s::jsonb)",(user_id,json.dumps(payload)))
        if body.balance is not None and body.equity is not None:
            # Keep account metrics tied to the actual MT5 account.
            conn.execute(
                """UPDATE account_state
                   SET balance=%s, equity=%s,
                       today_pl=COALESCE(%s, today_pl),
                       updated_at=now()
                   WHERE user_id=%s""",
                (float(body.balance), float(body.equity), float(body.today_pl) if body.today_pl is not None else None, user_id),
            )
    return {"ok":True,**payload}

@router.post("/market-data")
def market_data(body:MarketData,x_bridge_secret:str|None=Header(default=None)):
    user_id=require_bridge(x_bridge_secret,body.user_id)
    if body.timeframe not in ("5m","15m","1h"):
        raise HTTPException(400,"Unsupported timeframe; use 5m, 15m, or 1h")
    incoming=body.candles[-6000:]
    if not incoming:
        raise HTTPException(400,"No candles supplied")

    symbol=body.symbol.upper()
    # Merge by candle timestamp. This lets the Windows bridge upload a small
    # recent window every minute while preserving the larger validation history.
    with connection() as conn:
        row=conn.execute(
            "SELECT candles FROM bridge_market_data WHERE user_id=%s AND symbol=%s AND timeframe=%s",
            (user_id,symbol,body.timeframe)
        ).fetchone()

        existing=[]
        if row:
            existing=row[0] if isinstance(row[0],list) else json.loads(row[0])

        merged={}
        for candle in existing:
            if candle.get("time") is not None:
                merged[int(candle["time"])]=candle
        for candle in incoming:
            if candle.get("time") is not None:
                merged[int(candle["time"])]=candle

        candles=[merged[key] for key in sorted(merged)][-6000:]
        conn.execute("""INSERT INTO bridge_market_data (user_id,symbol,timeframe,candles,updated_at)
                        VALUES (%s,%s,%s,%s::jsonb,now())
                        ON CONFLICT (user_id,symbol,timeframe) DO UPDATE
                        SET candles=EXCLUDED.candles,updated_at=now()""",
                     (user_id,symbol,body.timeframe,json.dumps(candles)))

    return {"ok":True,"symbol":symbol,"timeframe":body.timeframe,"count":len(candles),"received":len(incoming)}

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

    # Fetch the completed command so notification payloads can include the
    # actual MT5 ticket/result.
    with connection() as conn:
        cmd=conn.execute(
            "SELECT user_id,command_type,payload FROM bridge_commands WHERE id=%s",
            (body.command_id,)
        ).fetchone()
    if cmd and cmd[1]=="open_market":
        payload=cmd[2] or {}
        if body.status=="completed":
            result=body.result or {}
            notification_event(user_id,"notification_trade_opened",{
                "symbol":payload.get("symbol"),
                "side":payload.get("side"),
                "entry":result.get("price"),
                "stop_loss":result.get("stop_loss",payload.get("stop_loss")),
                "take_profit":result.get("take_profit",payload.get("take_profit")),
                "ticket":result.get("ticket"),
                "ai_approved":payload.get("reason")=="TradeGuard AI Auto-Approval",
            })
            send_push(
                user_id,
                "TradeGuard · Trade opened",
                f"{payload.get('side')} {payload.get('symbol')} · Ticket #{result.get('ticket','—')} · Protected",
                {"type":"trade_opened","ticket":result.get("ticket"),"symbol":payload.get("symbol"),"side":payload.get("side")}
            )
        else:
            send_push(
                user_id,
                "TradeGuard · Execution failed",
                f"{payload.get('side')} {payload.get('symbol')} was not opened: {(body.result or {}).get('error','unknown error')}",
                {"type":"trade_execution_failed","symbol":payload.get("symbol"),"side":payload.get("side")}
            )

    return {"ok":True,"command_id":body.command_id,"status":body.status}
