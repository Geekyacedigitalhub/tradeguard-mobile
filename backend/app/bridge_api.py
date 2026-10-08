import json
import os
import hashlib
from uuid import UUID
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from .db import connection
from .notifications_api import notification_event, send_push
from .learning import open_broker_trade, close_broker_trade

router=APIRouter(prefix="/v1/bridge",tags=["mt5-bridge"])

def _upsert_by_bridge_id(conn, table, bridge_id, values):
    if table=="bridge_credentials":
        updated=conn.execute(
            """UPDATE bridge_credentials
               SET user_id=%s,token_hash=%s,created_at=now(),revoked_at=NULL
               WHERE bridge_id=%s""",
            (values[0],values[1],bridge_id),
        )
        if updated.rowcount == 0:
            conn.execute(
                """INSERT INTO bridge_credentials
                   (bridge_id,user_id,token_hash,created_at,revoked_at)
                   VALUES (%s,%s,%s,now(),NULL)""",
                (bridge_id,values[0],values[1]),
            )
        return
    if table=="bridge_pairings":
        updated=conn.execute(
            "UPDATE bridge_pairings SET user_id=%s,updated_at=now() WHERE bridge_id=%s",
            (values[0],bridge_id),
        )
        if updated.rowcount == 0:
            conn.execute(
                "INSERT INTO bridge_pairings (bridge_id,user_id,updated_at) VALUES (%s,%s,now())",
                (bridge_id,values[0]),
            )
        return
    raise ValueError("Unsupported bridge upsert table")

BRIDGE_SECRET=os.getenv("MT5_BRIDGE_SECRET")
_HEARTBEAT_CACHE={}
_BRIDGE_IDENTITY_CACHE={}
_BRIDGE_IDENTITY_CACHE_TTL=30

def require_bridge(secret,user_id,bridge_id="cloud-mt5-ea",token=None):
    if token:
        token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest()
        with connection() as conn:
            row=conn.execute(
                "SELECT user_id FROM bridge_credentials WHERE bridge_id=%s AND token_hash=%s AND revoked_at IS NULL LIMIT 1",
                (bridge_id,token_hash)
            ).fetchone()
        if not row:
            raise HTTPException(401,"Invalid bridge token")
        return str(row[0])
    if not BRIDGE_SECRET or not secret or secret != BRIDGE_SECRET:
        raise HTTPException(401,"Invalid bridge credentials")
    import time
    cached=_BRIDGE_IDENTITY_CACHE.get(bridge_id)
    if cached and time.monotonic()-cached[1] < _BRIDGE_IDENTITY_CACHE_TTL:
        return cached[0]
    with connection() as conn:
        row=conn.execute("SELECT user_id FROM bridge_pairings WHERE bridge_id=%s LIMIT 1").fetchone()
    if row:
        resolved=str(row[0])
        _BRIDGE_IDENTITY_CACHE[bridge_id]=(resolved,time.monotonic())
        return resolved
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

class PairingExchange(BaseModel):
    bridge_id:str="cloud-mt5-ea"
    code:str

@router.post("/exchange-pairing")
def exchange_pairing(body:PairingExchange):
    bridge_id=(body.bridge_id or "cloud-mt5-ea").strip()[:100] or "cloud-mt5-ea"
    code=(body.code or "").strip()
    if len(code)!=8 or not code.isdigit():
        raise HTTPException(400,"Invalid pairing code")
    code_hash=hashlib.sha256(code.encode("utf-8")).hexdigest()
    with connection() as conn:
        row=conn.execute(
            """SELECT user_id FROM bridge_pairing_codes
               WHERE bridge_id=%s AND code_hash=%s
                 AND used_at IS NULL AND expires_at > now()
               LIMIT 1""",
            (bridge_id,code_hash)
        ).fetchone()
        if not row:
            raise HTTPException(404,"Pairing code not found or expired")
        user_id=str(row[0])
        conn.execute(
            "UPDATE bridge_pairing_codes SET used_at=now() WHERE bridge_id=%s AND code_hash=%s AND used_at IS NULL",
            (bridge_id,code_hash)
        )
        import secrets
        token=secrets.token_urlsafe(32)
        token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest()
        _upsert_by_bridge_id(conn,"bridge_credentials",bridge_id,(user_id,token_hash))
        _upsert_by_bridge_id(conn,"bridge_pairings",bridge_id,(user_id,))
    _BRIDGE_IDENTITY_CACHE.pop(bridge_id,None)
    return {"ok":True,"bridge_id":bridge_id,"user_id":user_id,"token":token}

class BootstrapExchange(BaseModel):
    bridge_id:str="cloud-mt5-ea"
    bootstrap_key:str

@router.post("/exchange-bootstrap")
def exchange_bootstrap(body:BootstrapExchange):
    bridge_id=(body.bridge_id or "cloud-mt5-ea").strip()[:100] or "cloud-mt5-ea"
    bootstrap_key=(body.bootstrap_key or "").strip()
    if len(bootstrap_key) < 32:
        raise HTTPException(400,"Invalid cloud EA bootstrap key")
    token_hash=hashlib.sha256(bootstrap_key.encode("utf-8")).hexdigest()
    with connection() as conn:
        row=conn.execute(
            """SELECT user_id FROM bridge_bootstrap_tokens
               WHERE bridge_id=%s AND token_hash=%s AND revoked_at IS NULL
               LIMIT 1""",
            (bridge_id,token_hash),
        ).fetchone()
        if not row:
            raise HTTPException(401,"Invalid cloud EA bootstrap key")
        user_id=str(row[0])
        import secrets
        token=secrets.token_urlsafe(32)
        runtime_hash=hashlib.sha256(token.encode("utf-8")).hexdigest()
        _upsert_by_bridge_id(conn,"bridge_credentials",bridge_id,(user_id,runtime_hash))
        _upsert_by_bridge_id(conn,"bridge_pairings",bridge_id,(user_id,))
    _BRIDGE_IDENTITY_CACHE.pop(bridge_id,None)
    return {"ok":True,"bridge_id":bridge_id,"user_id":user_id,"token":token}

@router.get("/pairing")
def pairing(bridge_id:str="cloud-mt5-ea",x_bridge_secret:str|None=Header(default=None)):
    if not BRIDGE_SECRET or not x_bridge_secret or x_bridge_secret != BRIDGE_SECRET:
        raise HTTPException(401,"Invalid bridge credentials")
    bridge_id=(bridge_id or "cloud-mt5-ea").strip()[:100]
    with connection() as conn:
        row=conn.execute("SELECT user_id,updated_at FROM bridge_pairings WHERE bridge_id=%s",(bridge_id,)).fetchone()
    if not row:
        return {"paired":False,"bridge_id":bridge_id,"user_id":None}
    return {"paired":True,"bridge_id":bridge_id,"user_id":str(row[0]),"updated_at":row[1]}

@router.post("/heartbeat")
def heartbeat(body:Heartbeat,x_bridge_secret:str|None=Header(default=None),x_bridge_token:str|None=Header(default=None)):
    user_id=require_bridge(x_bridge_secret,body.user_id,token=x_bridge_token)
    payload={"connected":body.connected,"provider":"MT5","environment":body.environment,"account":body.account,"terminal":body.terminal,"balance":body.balance,"equity":body.equity,"today_pl":body.today_pl,"positions":body.positions}

    # Detect MT5 positions that disappeared between heartbeats. This catches
    # broker-side closes such as SL/TP, manual closes, and other terminal
    # exits even when the mobile app did not initiate the close.
    previous_positions=[]
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
            close_broker_trade(user_id,position.get("ticket"),price,pnl,reason)
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

    # Avoid writing an identical heartbeat snapshot repeatedly. Account state
    # is still refreshed every heartbeat, while broker_connection history only
    # records meaningful changes.
    heartbeat_key=str(user_id)
    # Store a broker snapshot only when connection/account/position identity
    # changes. Live prices and P/L are intentionally excluded from this
    # comparison because they change frequently but are not needed for the
    # historical connection record or close-detection snapshot.
    snapshot_key={
        "connected":body.connected,
        "account":body.account,
        "environment":body.environment,
        "terminal":body.terminal,
        "positions":[
            {
                "ticket":p.get("ticket"),
                "symbol":p.get("symbol"),
                "side":p.get("side"),
                "volume":p.get("volume"),
                "price_open":p.get("price_open"),
                "stop_loss":p.get("stop_loss"),
                "take_profit":p.get("take_profit"),
            }
            for p in body.positions
        ],
    }
    previous_cached=_HEARTBEAT_CACHE.get(heartbeat_key)
    snapshot_changed=previous_cached != snapshot_key
    if snapshot_changed:
        _HEARTBEAT_CACHE[heartbeat_key]=snapshot_key

    if snapshot_changed or (body.balance is not None and body.equity is not None):
        with connection() as conn:
            if snapshot_changed:
                conn.execute(
                    "INSERT INTO audit_events (user_id,event_type,payload) VALUES (%s,'broker_connection',%s::jsonb)",
                    (user_id,json.dumps(payload)),
                )
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
def market_data(body:MarketData,x_bridge_secret:str|None=Header(default=None),x_bridge_token:str|None=Header(default=None)):
    user_id=require_bridge(x_bridge_secret,body.user_id,token=x_bridge_token)
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
def commands(
    x_bridge_secret:str|None=Header(default=None),
    x_bridge_user:str|None=Header(default=None),
    x_bridge_id:str|None=Header(default=None),
    x_bridge_token:str|None=Header(default=None),
    limit:int=10,
):
    user_id=require_bridge(x_bridge_secret,x_bridge_user,x_bridge_id or "cloud-mt5-ea",token=x_bridge_token)
    limit=max(1,min(limit,50))
    with connection() as conn:
        rows=conn.execute(
            """WITH claimed AS (
                   SELECT id
                   FROM bridge_commands
                   WHERE status='pending' AND user_id=%s
                   ORDER BY id
                   LIMIT %s
                   FOR UPDATE SKIP LOCKED
               )
               UPDATE bridge_commands
               SET status='claimed',claimed_at=now()
               WHERE id IN (SELECT id FROM claimed)
               RETURNING id,user_id,command_type,payload,created_at""",
            (user_id,limit)
        ).fetchall()
    return {"commands":[{"id":r[0],"user_id":str(r[1]),"type":r[2],"payload":r[3],"created_at":r[4]} for r in rows]}

@router.post("/commands/result")
def command_result(body:CommandResult,x_bridge_secret:str|None=Header(default=None),x_bridge_user:str|None=Header(default=None),x_bridge_id:str|None=Header(default=None),x_bridge_token:str|None=Header(default=None)):
    user_id=require_bridge(x_bridge_secret,x_bridge_user,x_bridge_id or "cloud-mt5-ea",token=x_bridge_token)
    if body.status not in ("completed","failed"):
        raise HTTPException(400,"Status must be completed or failed")
    # Complete the command and return its type/payload in the same transaction.
    # This avoids a second Neon round-trip on every bridge command result.
    with connection() as conn:
        updated=conn.execute("""UPDATE bridge_commands SET status=%s,completed_at=now(),result=%s::jsonb WHERE id=%s AND user_id=%s AND status='claimed' RETURNING user_id,command_type,payload""",(body.status,json.dumps(body.result),body.command_id,user_id)).fetchone()
    if not updated:
        raise HTTPException(404,"Bridge command not found or already completed")
    cmd=updated
    if cmd and cmd[1]=="open_market":
        payload=cmd[2] or {}
        if body.status=="completed":
            result=body.result or {}
            ticket=result.get("ticket")
            if ticket is not None:
                open_broker_trade(user_id,ticket,payload.get("symbol"),payload.get("side"),
                    result.get("price") or payload.get("entry"),result.get("stop_loss") or payload.get("stop_loss"),
                    result.get("take_profit") or payload.get("take_profit"),payload.get("learning_context") or {})
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
