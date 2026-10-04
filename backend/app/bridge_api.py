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
        normalized=str(UUID(user_id))
    except (ValueError,TypeError):
        raise HTTPException(400,"Invalid bridge user id")

    # A fresh Neon database may not contain the user's old local account row.
    # The bridge secret plus a valid UUID are sufficient to restore that identity
    # so existing JWTs and bridge heartbeats can continue working after a DB move.
    with connection() as conn:
        conn.execute(
            """INSERT INTO users (id,email,password_hash,display_name)
               VALUES (%s,%s,%s,%s)
               ON CONFLICT (id) DO NOTHING""",
            (normalized, f"legacy-{normalized}@tradeguard.local", "bridge-provisioned", "TradeGuard User"),
        )
        conn.execute(
            """INSERT INTO account_state (user_id) VALUES (%s)
               ON CONFLICT (user_id) DO NOTHING""",
            (normalized,),
        )
        conn.execute(
            """INSERT INTO bot_state (user_id) VALUES (%s)
               ON CONFLICT (user_id) DO NOTHING""",
            (normalized,),
        )
    return normalized

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

    # Detect MT5 positions that disappeared between heartbeats. This catches
    # broker-side closes such as SL/TP, manual closes, and other terminal
    # exits even when the mobile app did not initiate the close.
    if body.connected:
        with connection() as conn:
            previous=conn.execute(
                """SELECT payload->'positions' FROM audit_events
                   WHERE user_id=%s AND event_type='broker_connection'
                   ORDER BY created_at DESC LIMIT 1""",
                (user_id,)
            ).fetchone()
        previous_positions=(previous[0] or []) if previous else []
        current_tickets={str(p.get("ticket")) for p in body.positions if p.get("ticket") is not None}
        closed=[p for p in previous_positions if p.get("ticket") is not None and str(p.get("ticket")) not in current_tickets]

        for position in closed:
            side=str(position.get("side","")).upper()
            price=float(position.get("price_current") or position.get("price_open") or 0)
            stop_loss=float(position.get("stop_loss") or 0)
            take_profit=float(position.get("take_profit") or 0)
            reason="closed"
            if side=="BUY":
                if take_profit and price >= take_profit: reason="take_profit"
                elif stop_loss and price <= stop_loss: reason="stop_loss"
            elif side=="SELL":
                if take_profit and price <= take_profit: reason="take_profit"
                elif stop_loss and price >= stop_loss: reason="stop_loss"

            label="Take profit" if reason=="take_profit" else ("Stop loss" if reason=="stop_loss" else "Trade")
            symbol=position.get("symbol","MT5")
            pnl=float(position.get("profit") or 0)
            notification_event(user_id,"notification_trade_closed",{
                "symbol":symbol,
                "side":side,
                "ticket":position.get("ticket"),
                "reason":reason,
                "exit":price,
                "pnl":pnl,
                "source":"MT5",
            })
            send_push(
                user_id,
                f"TradeGuard · {label} hit" if reason in ("take_profit","stop_loss") else f"TradeGuard · {symbol} closed",
                f"{side} {symbol} · Ticket #{position.get('ticket')} · P/L: {pnl:.2f}",
                {"type":"trade_closed","ticket":position.get("ticket"),"symbol":symbol,"side":side,"reason":reason,"pnl":pnl,"source":"MT5"},
            )

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
    incoming=body.candles[-600:]
    if not incoming:
        raise HTTPException(400,"No candles supplied")

    symbol=body.symbol.upper()
    # The bridge sends a rolling recent window. Re-reading the previous
    # JSON document on every upload wastes Neon network transfer, so store only
    # the newest window directly. Long historical validation data comes from
    # the cloud candle store, not this broker-specific cache.
    candles=incoming[-600:]
    with connection() as conn:
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
