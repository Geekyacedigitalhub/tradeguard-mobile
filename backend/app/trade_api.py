from fastapi import APIRouter, Depends, HTTPException
from .auth import current_user
from .db import connection
from .risk_api import approve_trade
from .trade_manager import list_positions, close_position, open_paper_position

router = APIRouter(prefix="/v1/trades", tags=["trades"])

def serialize(p):
    return {k:v for k,v in p.__dict__.items() if k != "user_id"}

@router.get("")
def trades(status: str | None = None, user=Depends(current_user)):
    return {"trades":[serialize(p) for p in list_positions(status,user["id"])]}

@router.post("/open")
def open_trade(signal: dict, user=Depends(current_user)):
    with connection() as conn:
        account=conn.execute("SELECT balance,equity,today_pl,drawdown FROM account_state WHERE user_id=%s",(user["id"],)).fetchone()
        risk=conn.execute("SELECT risk_per_trade,daily_loss_limit,max_open_trades,max_drawdown FROM bot_state WHERE user_id=%s",(user["id"],)).fetchone()
    if not account or not risk: raise HTTPException(500,"Account state is not initialized")
    open_count=len(list_positions("open",user["id"]))
    decision=approve_trade(signal,balance=float(account[0]),equity=float(account[1]),today_pnl_percent=float(account[2])/max(float(account[0]),1)*100,drawdown_percent=float(account[3]),open_trades=open_count,risk_per_trade=float(risk[0]),daily_loss_limit=float(risk[1]),max_open_trades=int(risk[2]),max_drawdown=float(risk[3]))
    if not decision["approved"]:
        raise HTTPException(409,decision["reason"])
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
