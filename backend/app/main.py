import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field
from .auth import current_user
from .auth_api import router as auth_router
from .notifications_api import router as notifications_router, send_push, notification_event
from .db import connection
from .market_data import candles_for, latest_price
from .strategy import analyze
from .risk_api import approve_trade
from .trade_api import router as trade_router
from .trade_manager import mark_prices, list_positions, open_paper_position

MARKETS=["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT"]

async def price_monitor():
    while True:
        try:
            symbols={p.symbol.replace("/USD","USDT") for p in list_positions("open")}
            if symbols:
                prices={}
                for symbol in symbols:
                    try: prices[symbol]=await latest_price(symbol)
                    except Exception: pass
                mark_prices(prices)
        except Exception:
            pass
        await asyncio.sleep(15)

def recent_signal_exists(user_id,symbol,action,minutes=10):
    with connection() as conn:
        row=conn.execute(
            "SELECT 1 FROM signals WHERE user_id=%s AND symbol=%s AND action=%s AND created_at >= now() - (%s * interval '1 minute') LIMIT 1",
            (user_id,symbol,action,minutes)
        ).fetchone()
    return bool(row)

async def auto_trade_cycle():
    try:
        with connection() as conn:
            users=conn.execute("SELECT user_id,mode FROM bot_state WHERE running=true AND emergency_stopped=false").fetchall()
        for user_id, mode in users:
            if mode not in ("signals_only","semi_auto","full_auto","auto"):
                continue
            open_now=list_positions("open",str(user_id))
            for symbol in MARKETS:
                if any(p.symbol == symbol.replace("USDT","/USD") for p in open_now):
                    continue
                try:
                    signal=analyze(await candles_for(symbol))
                    if signal.get("signal") not in ("BUY","SELL"):
                        continue
                    signal_symbol=signal.get("symbol",symbol.replace("USDT","/USD"))
                    if recent_signal_exists(user_id,signal_symbol,signal.get("signal")):
                        continue
                    with connection() as conn:
                        account=conn.execute("SELECT balance,equity,today_pl,drawdown FROM account_state WHERE user_id=%s",(user_id,)).fetchone()
                        risk=conn.execute("SELECT risk_per_trade,daily_loss_limit,max_open_trades,max_drawdown FROM bot_state WHERE user_id=%s",(user_id,)).fetchone()
                    if not account or not risk:
                        continue
                    decision=approve_trade(
                        signal,
                        balance=float(account[0]),
                        equity=float(account[1]),
                        today_pnl_percent=(float(account[2])/max(float(account[0]),1))*100,
                        drawdown_percent=float(account[3]),
                        open_trades=len(list_positions("open",str(user_id))),
                        risk_per_trade=float(risk[0]),
                        daily_loss_limit=float(risk[1]),
                        max_open_trades=int(risk[2]),
                        max_drawdown=float(risk[3])
                    )
                    with connection() as conn:
                        conn.execute(
                            "INSERT INTO signals (user_id,symbol,action,score,reason,entry,stop_loss,take_profit) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                            (user_id,signal_symbol,signal.get("signal"),float(signal.get("score") or 0),signal.get("reason"),signal.get("entry"),signal.get("stop_loss"),signal.get("take_profit"))
                        )
                    notification_event(user_id,"notification_signal",{"symbol":signal.get("symbol",symbol),"action":signal.get("signal"),"score":signal.get("score"),"reason":signal.get("reason")})
                    send_push(user_id,f"{signal.get("signal")} signal · {signal.get("symbol",symbol)}",str(signal.get("reason") or "Trade signal detected"),{"type":"signal","symbol":signal.get("symbol",symbol),"action":signal.get("signal")})
                    if decision["approved"] and mode in ("full_auto","auto"):
                        position=open_paper_position(str(user_id),signal,float(decision["quantity"]))
                        notification_event(user_id,"notification_trade_opened",{"symbol":position.symbol,"side":position.side,"entry":position.entry,"stop_loss":position.stop_loss,"take_profit":position.take_profit})
                        send_push(user_id,f"Trade opened · {position.symbol}",f"{position.side} at {position.entry}",{"type":"trade_opened","symbol":position.symbol})
                    elif mode=="semi_auto":
                        notification_event(user_id,"notification_trade_approval_needed",{"symbol":signal.get("symbol",symbol),"action":signal.get("signal"),"quantity":decision.get("quantity"),"reason":"Risk checks passed; manual approval required"})
                except Exception:
                    continue
    except Exception:
        pass

async def trading_worker():
    while True:
        await auto_trade_cycle()
        await asyncio.sleep(60)

@asynccontextmanager
async def lifespan(app):
    price_task=asyncio.create_task(price_monitor())
    trade_task=asyncio.create_task(trading_worker())
    yield
    price_task.cancel()
    trade_task.cancel()

app=FastAPI(title="TradeGuard API",version="0.6.0",lifespan=lifespan)
app.include_router(auth_router)
app.include_router(notifications_router)
app.include_router(trade_router)

@app.get("/v1/broker")
def broker_status(user=Depends(current_user)):
    with connection() as conn:
        row=conn.execute("SELECT payload FROM audit_events WHERE user_id=%s AND event_type='broker_connection' ORDER BY created_at DESC LIMIT 1",(user["id"],)).fetchone()
    if not row:
        return {"connected":False,"provider":"none","environment":"paper","message":"No live broker is connected. Paper trading remains active."}
    payload=row[0] or {}
    return {"connected":bool(payload.get("connected",False)),"provider":payload.get("provider","none"),"environment":payload.get("environment","paper"),"account":payload.get("account")}

class RiskSettings(BaseModel):
    risk_per_trade:float=Field(0.5,ge=0.1,le=5)
    daily_loss_limit:float=Field(2.0,ge=0.5,le=20)
    max_open_trades:int=Field(3,ge=1,le=20)
    max_drawdown:float=Field(5.0,ge=1,le=50)

@app.get("/health")
def health(): return {"ok":True,"service":"tradeguard-api","time":datetime.now(timezone.utc)}

@app.get("/v1/account")
def account(user=Depends(current_user)):
    with connection() as conn:
        row=conn.execute("SELECT balance,equity,today_pl,drawdown,currency FROM account_state WHERE user_id=%s",(user["id"],)).fetchone()
        bot=conn.execute("SELECT running,risk_per_trade,daily_loss_limit,max_open_trades,max_drawdown FROM bot_state WHERE user_id=%s",(user["id"],)).fetchone()
        open_count=conn.execute("SELECT COUNT(*) FROM positions WHERE user_id=%s AND status='open'",(user["id"],)).fetchone()[0]
    if not row or not bot: raise HTTPException(500,"Account state is not initialized")
    return {"balance":float(row[0]),"equity":float(row[1]),"today_pl":float(row[2]),"drawdown":float(row[3]),"currency":row[4],"bot":{"running":bool(bot[0]),"risk_per_trade":float(bot[1]),"daily_loss_limit":float(bot[2]),"max_open_trades":int(bot[3]),"max_drawdown":float(bot[4]),"open_trades":int(open_count)}}

@app.get("/v1/markets")
async def get_markets(user=Depends(current_user)):
    results=[]
    for symbol in MARKETS:
        try:
            result=analyze(await candles_for(symbol))
            results.append({"symbol":symbol.replace("USDT","/USD"),**result})
        except Exception as exc:
            results.append({"symbol":symbol.replace("USDT","/USD"),"signal":"NO TRADE","score":0,"reason":f"Market data unavailable: {type(exc).__name__}","entry":None,"stop_loss":None,"take_profit":None})
    return results

@app.post("/v1/risk/check")
def risk_check(signal:dict,user=Depends(current_user)):
    with connection() as conn:
        account_row=conn.execute("SELECT balance,equity,today_pl,drawdown FROM account_state WHERE user_id=%s",(user["id"],)).fetchone()
        risk=conn.execute("SELECT risk_per_trade,daily_loss_limit,max_open_trades,max_drawdown FROM bot_state WHERE user_id=%s",(user["id"],)).fetchone()
    if not account_row or not risk: raise HTTPException(500,"Risk state is not initialized")
    return approve_trade(signal,balance=float(account_row[0]),equity=float(account_row[1]),risk_per_trade=float(risk[0]),daily_loss_limit=float(risk[1]),max_open_trades=int(risk[2]),max_drawdown=float(risk[3]))

@app.get("/v1/signals")
async def get_signals(user=Depends(current_user)):
    markets=await get_markets(user)
    return {"signals":[m for m in markets if m["signal"] in ("BUY","SELL")]}

@app.get("/v1/bot")
def get_bot(user=Depends(current_user)):
    with connection() as conn:
        row=conn.execute("SELECT running,emergency_stopped,mode,risk_per_trade,daily_loss_limit,max_open_trades,max_drawdown,updated_at FROM bot_state WHERE user_id=%s",(user["id"],)).fetchone()
    if not row: raise HTTPException(500,"Bot state is not initialized")
    return {"running":row[0],"emergency_stopped":row[1],"mode":row[2],"risk_per_trade":float(row[3]),"daily_loss_limit":float(row[4]),"max_open_trades":int(row[5]),"max_drawdown":float(row[6]),"updated_at":row[7]}

class ModeSettings(BaseModel):
    mode: str

@app.put("/v1/bot/mode")
def update_mode(settings: ModeSettings, user=Depends(current_user)):
    allowed={"signals_only","semi_auto","full_auto"}
    if settings.mode not in allowed:
        raise HTTPException(400,"Mode must be signals_only, semi_auto, or full_auto")
    with connection() as conn:
        conn.execute("UPDATE bot_state SET mode=%s,updated_at=now() WHERE user_id=%s",(settings.mode,user["id"]))
    return get_bot(user)

@app.post("/v1/bot/start")
def start_bot(user=Depends(current_user)):
    with connection() as conn:
        row=conn.execute("SELECT emergency_stopped FROM bot_state WHERE user_id=%s",(user["id"],)).fetchone()
        if not row: raise HTTPException(500,"Bot state is not initialized")
        if row[0]: raise HTTPException(409,"Emergency stop is active. Reset it before starting the bot.")
        conn.execute("UPDATE bot_state SET running=true,updated_at=now() WHERE user_id=%s",(user["id"],))
    return get_bot(user)

@app.post("/v1/bot/stop")
def stop_bot(user=Depends(current_user)):
    with connection() as conn: conn.execute("UPDATE bot_state SET running=false,updated_at=now() WHERE user_id=%s",(user["id"],))
    return get_bot(user)

@app.post("/v1/bot/emergency-stop")
def emergency_stop(user=Depends(current_user)):
    with connection() as conn: conn.execute("UPDATE bot_state SET running=false,emergency_stopped=true,updated_at=now() WHERE user_id=%s",(user["id"],))
    notification_event(user["id"],"notification_emergency_stop",{"message":"Emergency stop activated"})
    send_push(user["id"],"Emergency stop activated","New trading has been disabled.",{"type":"emergency_stop"})
    return {"ok":True,"message":"New trading disabled and bot stopped","state":get_bot(user)}

@app.post("/v1/bot/reset-emergency")
def reset_emergency(user=Depends(current_user)):
    with connection() as conn: conn.execute("UPDATE bot_state SET emergency_stopped=false,updated_at=now() WHERE user_id=%s",(user["id"],))
    return get_bot(user)

@app.put("/v1/bot/risk")
def update_risk(settings:RiskSettings,user=Depends(current_user)):
    with connection() as conn:
        conn.execute("UPDATE bot_state SET risk_per_trade=%s,daily_loss_limit=%s,max_open_trades=%s,max_drawdown=%s,updated_at=now() WHERE user_id=%s",(settings.risk_per_trade,settings.daily_loss_limit,settings.max_open_trades,settings.max_drawdown,user["id"]))
    return get_bot(user)
