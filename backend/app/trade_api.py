from fastapi import APIRouter, Depends, HTTPException
from .auth import current_user
from .db import connection
from .risk_api import approve_trade
from .trade_manager import list_positions, close_position, open_paper_position
from .account_sync import live_account_metrics
def mt5_connected(user_id):
    with connection() as conn:
        row=conn.execute("SELECT payload,created_at FROM audit_events WHERE user_id=%s AND event_type='broker_connection' ORDER BY created_at DESC LIMIT 1",(user_id,)).fetchone()
    if not row:
        return False
    payload=row[0] or {}
    from datetime import datetime,timezone
    return bool(payload.get("connected")) and (datetime.now(timezone.utc)-row[1]).total_seconds()<=45

def queue_bridge_command(user_id,command_type,payload):
    with connection() as conn:
        row=conn.execute("INSERT INTO bridge_commands (user_id,command_type,payload) VALUES (%s,%s,%s::jsonb) RETURNING id",(user_id,command_type,__import__("json").dumps(payload))).fetchone()
    return int(row[0])


router = APIRouter(prefix="/v1/trades", tags=["trades"])

def serialize(p):
    return {k:v for k,v in p.__dict__.items() if k != "user_id"}

@router.get("")
def trades(status: str | None = None, user=Depends(current_user)):
    return {"trades":[serialize(p) for p in list_positions(status,user["id"])]}

@router.post("/open")
def open_trade(signal: dict, user=Depends(current_user)):
    account=live_account_metrics(user["id"])
    with connection() as conn:
        risk=conn.execute("SELECT risk_per_trade,daily_loss_limit,max_open_trades,max_drawdown FROM bot_state WHERE user_id=%s",(user["id"],)).fetchone()
    if not account or not risk: raise HTTPException(500,"Account state is not initialized")
    open_count=len(list_positions("open",user["id"]))
    decision=approve_trade(signal,balance=float(account["balance"]),equity=float(account["equity"]),today_pnl_percent=float(account["today_pl"])/max(float(account["balance"]),1)*100,drawdown_percent=float(account["drawdown"]),open_trades=open_count,risk_per_trade=float(risk[0]),daily_loss_limit=float(risk[1]),max_open_trades=int(risk[2]),max_drawdown=float(risk[3]))
    if not decision["approved"]:
        raise HTTPException(409,decision["reason"])
    if mt5_connected(user["id"]):
        command_id=queue_bridge_command(user["id"],"open_market",{"symbol":signal.get("mt5_symbol") or str(signal.get("symbol","")).replace("/",""),"side":signal.get("signal"),"volume":float(decision["quantity"]),"stop_loss":signal.get("stop_loss"),"take_profit":signal.get("take_profit")})
        return {"approved":True,"execution":"mt5_demo","pending":True,"command_id":command_id,"risk":decision}
    position=open_paper_position(user["id"],signal,float(decision["quantity"]))
    with connection() as conn:
        conn.execute("INSERT INTO signals (user_id,symbol,action,score,reason,entry,stop_loss,take_profit) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (user["id"],signal.get("symbol",""),signal.get("signal",""),float(signal.get("score") or 0),signal.get("reason"),signal.get("entry"),signal.get("stop_loss"),signal.get("take_profit")))
    return {"approved":True,"risk":decision,"trade":serialize(position)}

@router.post("/{position_id}/close")
def close_trade(position_id: int, user=Depends(current_user)):
    matches=[p for p in list_positions(user_id=user["id"]) if p.id == position_id]
    if not matches: raise HTTPException(404,"Position not found")
    return serialize(close_position(matches[0]))

@router.post("/close-all")
def close_all(user=Depends(current_user)):
    closed=[]
    for p in list_positions("open",user["id"]): closed.append(serialize(close_position(p)))
    return {"trades":closed}


@router.post("/account/switch")
def switch_broker_account(body: dict, user=Depends(current_user)):
    profile=str(body.get("profile","")).lower()
    if profile not in ("demo","live"):
        raise HTTPException(400,"Profile must be demo or live")
    if profile=="live" and body.get("confirmation")!="LIVE_TRADING":
        raise HTTPException(400,"Live account switch requires explicit confirmation")
    if not mt5_connected(user["id"]):
        raise HTTPException(409,"MT5 bridge is not connected")
    command_id=queue_bridge_command(user["id"],"switch_account",{"profile":profile})
    return {"queued":True,"profile":profile,"command_id":command_id}

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
        raise HTTPException(409,"MT5 bridge is not connected")
    command_id=queue_bridge_command(user["id"],"close_position",{"ticket":ticket})
    return {"queued":True,"execution":"mt5_demo","command_id":command_id,"ticket":ticket}
