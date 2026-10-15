from fastapi import APIRouter, Depends, HTTPException
from .auth import current_user
from .db import connection
from .risk_api import approve_trade
from .trade_manager import get_position, list_positions, close_position, open_paper_position
from .account_sync import live_account_metrics
from .risk_metrics import consecutive_losses
from .validation_gate import latest_validation_gate
from .profit_engine import evaluate_opportunity
from .learning import learning_gate
from .optimizer import optimizer_gate
from .execution import execution_snapshot, execution_provider
from .ctrader_service import manager as ctrader_manager
import time

_BROKER_CONNECTION_CACHE={}
_BROKER_CONNECTION_CACHE_TTL=5

def _broker_connection_snapshot(user_id):
    key=str(user_id)
    cached=_BROKER_CONNECTION_CACHE.get(key)
    now=time.monotonic()
    if cached and now-cached[0] < _BROKER_CONNECTION_CACHE_TTL:
        return cached[1]
    with connection() as conn:
        row=conn.execute("""SELECT ae.payload,ae.created_at,ast.updated_at FROM audit_events ae LEFT JOIN account_state ast ON ast.user_id=ae.user_id WHERE ae.user_id=%s AND ae.event_type='broker_connection' ORDER BY ae.created_at DESC LIMIT 1""",(user_id,)).fetchone()
    if not row:
        snapshot={"connected":False,"positions":None,"payload":{}}
    else:
        from datetime import datetime,timezone
        payload=row[0] or {}
        # cTrader heartbeat writes this event directly; account_state.updated_at
        # is not authoritative for cloud connection freshness.
        last_seen=row[1]
        age=(datetime.now(timezone.utc)-last_seen).total_seconds()
        snapshot={
            "connected":bool(payload.get("connected")) and age<=45 and payload.get("terminal")=="cTrader Cloud",
            "positions":payload.get("positions") if isinstance(payload.get("positions"),list) else None,
            "payload":payload,
            "last_seen":last_seen,
            "age_seconds":max(0.0,round(age,1)),
        }
    _BROKER_CONNECTION_CACHE[key]=(now,snapshot)
    return snapshot

def ctrader_connected(user_id):
    snapshot=_broker_connection_snapshot(user_id)
    # The selected cTrader cloud account is the only supported broker connection.
    return bool(snapshot["connected"])

def queue_bridge_command(user_id,command_type,payload):
    with connection() as conn:
        row=conn.execute("INSERT INTO bridge_commands (user_id,command_type,payload) VALUES (%s,%s,%s::jsonb) RETURNING id",(user_id,command_type,__import__("json").dumps(payload))).fetchone()
    return int(row[0])


router = APIRouter(prefix="/v1/trades", tags=["trades"])

def serialize(p):
    return {k:v for k,v in p.__dict__.items() if k != "user_id"}

@router.get("")
def trades(status: str | None = None, user=Depends(current_user)):
    snapshot=_broker_connection_snapshot(user["id"])
    if ctrader_connected(user["id"]) and snapshot.get("positions") is not None:
        broker_positions=snapshot["positions"]
        if status in (None,"open"):
            return {"trades":broker_positions}
        if status=="closed":
            return {"trades":[]}
    return {"trades":[serialize(p) for p in list_positions(status,user["id"])]}

@router.post("/open")
def open_trade(signal: dict, user=Depends(current_user)):
    deep=signal.get("deep_analysis") or {}
    if deep.get("decision")!="TRADE CANDIDATE":
        raise HTTPException(409,"TradeGuard research gate: the deep analysis does not currently support execution.")
    symbol_key=str(signal.get("symbol","")).replace("/","")
    historical=latest_validation_gate(user["id"],symbol_key)
    if not historical.get("approved"):
        raise HTTPException(409,"TradeGuard historical evidence gate: "+str(historical.get("reason","validation required")))
    profit=evaluate_opportunity(signal,historical=historical)
    learning=learning_gate(user["id"],symbol_key,setup="TradeGuard MTF Price Action v2",
                           session=(signal.get("intelligence") or {}).get("session"),
                           regime=(signal.get("intelligence") or {}).get("regime"))
    optimizer=optimizer_gate(user["id"],symbol_key,setup="TradeGuard MTF Price Action v2",
                             session=(signal.get("intelligence") or {}).get("session"),
                             regime=(signal.get("intelligence") or {}).get("regime"))
    profit["learning"]=learning
    profit["optimizer"]=optimizer
    profit["risk_multiplier"]=round(
        float(profit.get("risk_multiplier") or 1.0)
        * float(learning.get("modifier") or 1.0)
        * float(optimizer.get("modifier") or 1.0),3)
    if not learning.get("approved") or not optimizer.get("approved"):
        profit["decision"]="WAIT"
        profit["tier"]="REJECT"
        profit.setdefault("vetoes",[]).append(learning.get("reason") or "Live learning gate rejected the setup.")
    if not optimizer.get("approved"):
        profit["decision"]="WAIT"
        profit["tier"]="REJECT"
        profit.setdefault("vetoes",[]).append(optimizer.get("reason") or "Optimizer rejected the setup.")
    if profit.get("decision")!="EXECUTE":
        raise HTTPException(409,"TradeGuard profit engine: "+"; ".join(profit.get("vetoes") or ["edge threshold not met"]))
    signal["profit_engine"]=profit
    account=live_account_metrics(user["id"])
    with connection() as conn:
        risk=conn.execute("SELECT risk_per_trade,daily_loss_limit,max_open_trades,max_drawdown FROM bot_state WHERE user_id=%s",(user["id"],)).fetchone()
    if not account: raise HTTPException(409,"Verified cTrader demo risk metrics are unavailable. No order was queued.")
    if not risk: raise HTTPException(500,"Risk settings are not initialized")
    open_count=len(list_positions("open",user["id"]))
    # When cTrader is connected, broker positions are the source of truth.
    broker_snapshot=_broker_connection_snapshot(user["id"])
    if broker_snapshot["connected"] and broker_snapshot["positions"] is not None:
        open_count=len(broker_snapshot["positions"])
    decision=approve_trade(signal,balance=float(account["balance"]),equity=float(account["equity"]),today_pnl_percent=float(account["today_pl"])/max(float(account["balance"]),1)*100,drawdown_percent=float(account["drawdown"]),open_trades=open_count,consecutive_losses=consecutive_losses(user["id"]),risk_per_trade=float(risk[0]) * float(profit.get("risk_multiplier",1.0)),daily_loss_limit=float(risk[1]),max_open_trades=int(risk[2]),max_drawdown=float(risk[3]))
    if not decision["approved"]:
        raise HTTPException(409,decision["reason"])
    provider=execution_provider(user["id"])
    if provider=="ctrader":
        raise HTTPException(
            409,
            "cTrader order submission is temporarily disabled until broker-volume sizing, "
            "selected demo-account validation, fresh quote checks, and mandatory stop-loss/"
            "take-profit protection are verified end-to-end. No order was queued.",
        )
    raise HTTPException(409,"No cloud execution terminal is connected. Trading is blocked until the cloud execution heartbeat is active.")

@router.post("/{position_id}/close")
def close_trade(position_id: int, user=Depends(current_user)):
    position=get_position(position_id,user["id"])
    if not position: raise HTTPException(404,"Position not found")
    return serialize(close_position(position))

@router.post("/close-all")
def close_all(user=Depends(current_user)):
    snapshot=execution_snapshot(user["id"])
    if snapshot["connected"]:
        if snapshot["provider"] == "ctrader":
            raise HTTPException(
                409,
                "cTrader close-all is disabled until each broker position is reconciled and its "
                "exact remaining volume is validated. No close command was queued.",
            )
        raise HTTPException(409,"Unsupported broker provider. No close command was queued.")
    raise HTTPException(409,"No cloud execution terminal is connected")


@router.post("/account/switch")
def switch_broker_account(body: dict, user=Depends(current_user)):
    raise HTTPException(
        409,
        "Select the account through the cTrader connection flow; automated trading remains disabled.",
    )

@router.get("/execution")
def execution_status(user=Depends(current_user)):
    snapshot=execution_snapshot(user["id"])
    return {
        "connected":snapshot["connected"],
        "provider":snapshot["provider"],
        "terminal":snapshot["terminal"],
        "environment":snapshot["environment"],
        "account":snapshot["account"],
        "last_heartbeat":snapshot["last_seen"],
        "heartbeat_age_seconds":snapshot["age_seconds"],
        "positions_count":len(snapshot["positions"]),
    }

@router.get("/connection")
def ctrader_connection_status(user=Depends(current_user)):
    with connection() as conn:
        row=conn.execute(
            "SELECT account_id,environment,expires_at,updated_at FROM ctrader_connections WHERE user_id=%s",
            (user["id"],),
        ).fetchone()
    if not row:
        return {"connected":False,"authorized":False,"provider":"ctrader_cloud","terminal":"cTrader Cloud"}
    return {
        "connected":bool(row[0]) and str(row[1] or "demo").lower()=="demo" and ctrader_manager.account_ready(str(row[1] or "demo"), int(row[0])),
        "authorized":True,
        "provider":"ctrader_cloud",
        "terminal":"cTrader Cloud",
        "account":row[0],
        "environment":row[1] or "demo",
        "expires_at":row[2],
        "updated_at":row[3],
    }

@router.get("/command/{command_id}")
def bridge_command_status(command_id: int, user=Depends(current_user)):
    with connection() as conn:
        row=conn.execute("""SELECT id,command_type,status,created_at,claimed_at,completed_at,result FROM bridge_commands WHERE id=%s AND user_id=%s""",(command_id,user["id"])).fetchone()
    if not row:
        raise HTTPException(404,"Bridge command not found")
    return {"id":row[0],"type":row[1],"status":row[2],"created_at":row[3],"claimed_at":row[4],"completed_at":row[5],"result":row[6]}

