import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field
from .auth import current_user
from .auth_api import router as auth_router
from .market_data import candles_for, latest_price
from .strategy import analyze
from .risk_api import approve_trade
from .trade_api import router as trade_router
from .trade_manager import mark_prices, list_positions

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

@asynccontextmanager
async def lifespan(app):
    task=asyncio.create_task(price_monitor())
    yield
    task.cancel()

app=FastAPI(title="TradeGuard API",version="0.5.0",lifespan=lifespan)
app.include_router(auth_router)
app.include_router(trade_router)

class RiskSettings(BaseModel):
    risk_per_trade:float=Field(0.5,ge=0.1,le=5)
    daily_loss_limit:float=Field(2.0,ge=0.5,le=20)
    max_open_trades:int=Field(3,ge=1,le=20)
    max_drawdown:float=Field(5.0,ge=1,le=50)

@app.get("/health")
def health(): return {"ok":True,"service":"tradeguard-api","time":datetime.now(timezone.utc)}

@app.get("/v1/account")
def account(user=Depends(current_user)):
    from .db import connection
    with connection() as conn:
        row=conn.execute("SELECT balance,equity,today_pl,drawdown,currency FROM account_state WHERE user_id=%s",(user["id"],)).fetchone()
        bot=conn.execute("SELECT running FROM bot_state WHERE user_id=%s",(user["id"],)).fetchone()
    if not row or not bot:
        raise HTTPException(500,"Account state is not initialized")
    return {"balance":float(row[0]),"equity":float(row[1]),"today_pl":float(row[2]),"drawdown":float(row[3]),"currency":row[4],"bot":{"running":bool(bot[0])}}

@app.get("/v1/markets")
async def get_markets(user=Depends(current_user)):
    results=[]
    for symbol in ["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT"]:
        try:
            result=analyze(await candles_for(symbol))
            results.append({"symbol":symbol.replace("USDT","/USD"),**result})
        except Exception as exc:
            results.append({"symbol":symbol.replace("USDT","/USD"),"signal":"NO TRADE","score":0,"reason":f"Market data unavailable: {type(exc).__name__}","entry":None,"stop_loss":None,"take_profit":None})
    return results

@app.post("/v1/risk/check")
def risk_check(signal:dict,user=Depends(current_user)):
    from .db import connection
    with connection() as conn:
        account_row=conn.execute("SELECT balance,equity,today_pl,drawdown FROM account_state WHERE user_id=%s",(user["id"],)).fetchone()
        risk=conn.execute("SELECT risk_per_trade,daily_loss_limit,max_open_trades,max_drawdown FROM bot_state WHERE user_id=%s",(user["id"],)).fetchone()
    if not account_row or not risk: raise HTTPException(500,"Risk state is not initialized")
    return approve_trade(signal,balance=float(account_row[0]),equity=float(account_row[1]),risk_per_trade=float(risk[0]),daily_loss_limit=float(risk[1]),max_open_trades=int(risk[2]),max_drawdown=float(risk[3]))

@app.get("/v1/signals")
async def get_signals(user=Depends(current_user)):
    markets=await get_markets(user); return {"signals":[m for m in markets if m["signal"] in ("BUY","SELL")]}

@app.get("/v1/bot")
def get_bot(user=Depends(current_user)):
    from .db import connection
    with connection() as conn:
        row=conn.execute("SELECT running,emergency_stopped,mode,risk_per_trade,daily_loss_limit,max_open_trades,max_drawdown,updated_at FROM bot_state WHERE user_id=%s",(user["id"],)).fetchone()
    if not row: raise HTTPException(500,"Bot state is not initialized")
    return {"running":row[0],"emergency_stopped":row[1],"mode":row[2],"risk_per_trade":float(row[3]),"daily_loss_limit":float(row[4]),"max_open_trades":int(row[5]),"max_drawdown":float(row[6]),"updated_at":row[7]}

@app.post("/v1/bot/start")
def start_bot(user=Depends(current_user)):
    from .db import connection
    with connection() as conn:
        row=conn.execute("SELECT emergency_stopped FROM bot_state WHERE user_id=%s",(user["id"],)).fetchone()
        if not row: raise HTTPException(500,"Bot state is not initialized")
        if row[0]: raise HTTPException(409,"Emergency stop is active. Reset it before starting the bot.")
        conn.execute("UPDATE bot_state SET running=true,updated_at=now() WHERE user_id=%s",(user["id"],))
    return get_bot(user)

@app.post("/v1/bot/stop")
def stop_bot(user=Depends(current_user)):
    from .db import connection
    with connection() as conn: conn.execute("UPDATE bot_state SET running=false,updated_at=now() WHERE user_id=%s",(user["id"],))
    return get_bot(user)

@app.post("/v1/bot/emergency-stop")
def emergency_stop(user=Depends(current_user)):
    from .db import connection
    with connection() as conn: conn.execute("UPDATE bot_state SET running=false,emergency_stopped=true,updated_at=now() WHERE user_id=%s",(user["id"],))
    return {"ok":True,"message":"New trading disabled and bot stopped","state":get_bot(user)}

@app.post("/v1/bot/reset-emergency")
def reset_emergency(user=Depends(current_user)):
    from .db import connection
    with connection() as conn: conn.execute("UPDATE bot_state SET emergency_stopped=false,updated_at=now() WHERE user_id=%s",(user["id"],))
    return get_bot(user)

@app.put("/v1/bot/risk")
def update_risk(settings:RiskSettings,user=Depends(current_user)):
    from .db import connection
    with connection() as conn:
        conn.execute("UPDATE bot_state SET risk_per_trade=%s,daily_loss_limit=%s,max_open_trades=%s,max_drawdown=%s,updated_at=now() WHERE user_id=%s",(settings.risk_per_trade,settings.daily_loss_limit,settings.max_open_trades,settings.max_drawdown,user["id"]))
    return get_bot(user)
