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
import time

_MT5_CONNECTION_CACHE={}
_MT5_CONNECTION_CACHE_TTL=5

def _broker_connection_snapshot(user_id):
    key=str(user_id)
    cached=_MT5_CONNECTION_CACHE.get(key)
    now=time.monotonic()
    if cached and now-cached[0] < _MT5_CONNECTION_CACHE_TTL:
        return cached[1]
    with connection() as conn:
        row=conn.execute("""SELECT ae.payload,ae.created_at,ast.updated_at FROM audit_events ae LEFT JOIN account_state ast ON ast.user_id=ae.user_id WHERE ae.user_id=%s AND ae.event_type='broker_connection' ORDER BY ae.created_at DESC LIMIT 1""",(user_id,)).fetchone()
    if not row:
        snapshot={"connected":False,"positions":None,"payload":{}}
    else:
        from datetime import datetime,timezone
        payload=row[0] or {}
        last_seen=row[2] or row[1]
        age=(datetime.now(timezone.utc)-last_seen).total_seconds()
        snapshot={
            "connected":bool(payload.get("connected")) and age<=45 and payload.get("terminal")=="MT5 Cloud EA",
            "positions":payload.get("positions") if isinstance(payload.get("positions"),list) else None,
            "payload":payload,
            "last_seen":last_seen,
            "age_seconds":max(0.0,round(age,1)),
        }
    _MT5_CONNECTION_CACHE[key]=(now,snapshot)
    return snapshot

def mt5_connected(user_id):
    snapshot=_broker_connection_snapshot(user_id)
    # Production execution is owned by the cloud MT5 EA. The old
    # Windows/Python bridge must never become the mobile fallback path.
    return bool(snapshot["connected"])

def mt5_connection_status(user_id):
    snapshot=_broker_connection_snapshot(user_id)
    payload=snapshot.get("payload") or {}
    connected=bool(snapshot.get("connected"))
    return {
        "connected":connected,
        "execution":"MT5_CLOUD_EA" if connected else "OFFLINE",
        "terminal":payload.get("terminal"),
        "environment":payload.get("environment"),
        "account":payload.get("account"),
        "last_heartbeat":snapshot.get("last_seen"),
        "heartbeat_age_seconds":snapshot.get("age_seconds"),
        "positions_count":len(snapshot.get("positions") or []),
    }

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
    if mt5_connected(user["id"]) and snapshot.get("positions") is not None:
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
    if not account or not risk: raise HTTPException(500,"Account state is not initialized")
    open_count=len(list_positions("open",user["id"]))
    # When MT5 is connected, broker positions are the source of truth.
    broker_snapshot=_broker_connection_snapshot(user["id"])
    if broker_snapshot["connected"] and broker_snapshot["positions"] is not None:
        open_count=len(broker_snapshot["positions"])
    decision=approve_trade(signal,balance=float(account["balance"]),equity=float(account["equity"]),today_pnl_percent=float(account["today_pl"])/max(float(account["balance"]),1)*100,drawdown_percent=float(account["drawdown"]),open_trades=open_count,consecutive_losses=consecutive_losses(user["id"]),risk_per_trade=float(risk[0]) * float(profit.get("risk_multiplier",1.0)),daily_loss_limit=float(risk[1]),max_open_trades=int(risk[2]),max_drawdown=float(risk[3]))
    if not decision["approved"]:
        raise HTTPException(409,decision["reason"])
    provider=execution_provider(user["id"])
    if provider=="mt5":
        command_id=queue_bridge_command(user["id"],"open_market",{"symbol":signal.get("mt5_symbol") or str(signal.get("symbol","")).replace("/",""),"side":signal.get("signal"),"volume":float(decision["quantity"]),"entry":signal.get("entry"),"stop_loss":signal.get("stop_loss"),"take_profit":signal.get("take_profit"),"learning_context":{"setup":"TradeGuard MTF Price Action v2","timeframe":"MTF","session":(signal.get("intelligence") or {}).get("session"),"regime":(signal.get("intelligence") or {}).get("regime"),"volatility":(signal.get("intelligence") or {}).get("volatility"),"edge_score":profit.get("edge_score"),"expectancy_r":profit.get("expectancy_r"),"risk_multiplier":profit.get("risk_multiplier")}})
        return {"approved":True,"execution":"mt5_cloud","pending":True,"command_id":command_id,"risk":decision}
    if provider=="ctrader":
        command_id=queue_bridge_command(user["id"],"open_market",{"symbol":signal.get("ctrader_symbol") or str(signal.get("symbol","")).replace("/",""),"side":signal.get("signal"),"risk_amount":float(decision["risk_amount"]),"quantity":float(decision["quantity"]),"execution_provider":"ctrader","entry":signal.get("entry"),"stop_loss":signal.get("stop_loss"),"take_profit":signal.get("take_profit"),"learning_context":{"setup":"TradeGuard MTF Price Action v2","timeframe":"MTF","session":(signal.get("intelligence") or {}).get("session"),"regime":(signal.get("intelligence") or {}).get("regime"),"volatility":(signal.get("intelligence") or {}).get("volatility"),"edge_score":profit.get("edge_score"),"expectancy_r":profit.get("expectancy_r"),"risk_multiplier":profit.get("risk_multiplier")}})
        return {"approved":True,"execution":"ctrader_cloud","pending":True,"command_id":command_id,"risk":decision}
    raise HTTPException(409,"No cloud execution terminal is connected. Trading is blocked until the cloud execution heartbeat is active.")
    with connection() as conn:
        conn.execute("INSERT INTO signals (user_id,symbol,action,score,reason,entry,stop_loss,take_profit) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (user["id"],signal.get("symbol",""),signal.get("signal",""),float(signal.get("score") or 0),signal.get("reason"),signal.get("entry"),signal.get("stop_loss"),signal.get("take_profit")))
    return {"approved":True,"risk":decision,"trade":serialize(position)}

@router.post("/{position_id}/close")
def close_trade(position_id: int, user=Depends(current_user)):
    position=get_position(position_id,user["id"])
    if not position: raise HTTPException(404,"Position not found")
    return serialize(close_position(position))

@router.post("/close-all")
def close_all(user=Depends(current_user)):
    snapshot=execution_snapshot(user["id"])
    if snapshot["connected"]:
        positions=snapshot.get("positions") or []
        commands=[]
        for position in positions:
            ticket=position.get("ticket") or position.get("id")
            if ticket is not None:
                commands.append(queue_bridge_command(user["id"],"close_position",{"ticket":int(ticket)}))
        return {"queued":True,"execution":snapshot["provider"],"command_ids":commands,"count":len(commands)}
    raise HTTPException(409,"No cloud execution terminal is connected")


@router.post("/account/switch")
def switch_broker_account(body: dict, user=Depends(current_user)):
    profile=str(body.get("profile","")).lower()
    if profile not in ("demo","live"):
        raise HTTPException(400,"Profile must be demo or live")
    if profile=="live" and body.get("confirmation")!="LIVE_TRADING":
        raise HTTPException(400,"Live account switch requires explicit confirmation")
    if not mt5_connected(user["id"]):
        raise HTTPException(409,"Cloud MT5 terminal is not connected")
    command_id=queue_bridge_command(user["id"],"switch_account",{"profile":profile})
    return {"queued":True,"execution":"mt5_cloud_ea","profile":profile,"command_id":command_id}

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
def mt5_connection(user=Depends(current_user)):
    return mt5_connection_status(user["id"])

@router.get("/command/{command_id}")
def bridge_command_status(command_id: int, user=Depends(current_user)):
    with connection() as conn:
        row=conn.execute("""SELECT id,command_type,status,created_at,claimed_at,completed_at,result FROM bridge_commands WHERE id=%s AND user_id=%s""",(command_id,user["id"])).fetchone()
    if not row:
        raise HTTPException(404,"Bridge command not found")
    return {"id":row[0],"type":row[1],"status":row[2],"created_at":row[3],"claimed_at":row[4],"completed_at":row[5],"result":row[6]}

@router.post("/mt5/{ticket}/close")
def close_mt5_trade(ticket: int, user=Depends(current_user)):
    if not mt5_connected(user["id"]):
        raise HTTPException(409,"Cloud MT5 terminal is not connected")
    command_id=queue_bridge_command(user["id"],"close_position",{"ticket":ticket})
    return {"queued":True,"execution":"mt5_cloud_ea","command_id":command_id,"ticket":ticket}
