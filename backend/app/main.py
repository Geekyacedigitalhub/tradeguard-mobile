import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from datetime import datetime, timezone
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

app=FastAPI(title="TradeGuard API",version="0.4.0",lifespan=lifespan)
app.include_router(trade_router)

class RiskSettings(BaseModel):
    risk_per_trade:float=Field(0.5,ge=0.1,le=5)
    daily_loss_limit:float=Field(2.0,ge=0.5,le=20)
    max_open_trades:int=Field(3,ge=1,le=20)
    max_drawdown:float=Field(5.0,ge=1,le=50)
class BotState(BaseModel):
    running:bool=False
    emergency_stopped:bool=False
    mode:str="semi_auto"
    risk:RiskSettings=RiskSettings()
    updated_at:datetime=datetime.now(timezone.utc)
state=BotState()

@app.get("/health")
def health(): return {"ok":True,"service":"tradeguard-api","time":datetime.now(timezone.utc)}
@app.get("/v1/account")
def account(): return {"balance":1000.0,"equity":1024.20,"today_pl":24.20,"drawdown":1.2,"currency":"USD","bot":{"running":state.running}}

@app.get("/v1/markets")
async def get_markets():
    results=[]
    for symbol in ["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT"]:
        try:
            result=analyze(await candles_for(symbol))
            results.append({"symbol":symbol.replace("USDT","/USD"),**result})
        except Exception as exc:
            results.append({"symbol":symbol.replace("USDT","/USD"),"signal":"NO TRADE","score":0,"reason":f"Market data unavailable: {type(exc).__name__}","entry":None,"stop_loss":None,"take_profit":None})
    return results

@app.post("/v1/risk/check")
def risk_check(signal:dict):
    return approve_trade(signal,balance=1000,equity=1000,risk_per_trade=state.risk.risk_per_trade,daily_loss_limit=state.risk.daily_loss_limit,max_open_trades=state.risk.max_open_trades,max_drawdown=state.risk.max_drawdown)
@app.get("/v1/signals")
async def get_signals():
    markets=await get_markets(); return {"signals":[m for m in markets if m["signal"] in ("BUY","SELL")]}

@app.get("/v1/bot")
def get_bot(): return {"running":state.running,"emergency_stopped":state.emergency_stopped,"mode":state.mode,**state.risk.model_dump(),"updated_at":state.updated_at}
@app.post("/v1/bot/start")
def start_bot():
    if state.emergency_stopped: raise HTTPException(409,"Emergency stop is active. Reset it before starting the bot.")
    state.running=True; state.updated_at=datetime.now(timezone.utc); return get_bot()
@app.post("/v1/bot/stop")
def stop_bot(): state.running=False; state.updated_at=datetime.now(timezone.utc); return get_bot()
@app.post("/v1/bot/emergency-stop")
def emergency_stop():
    state.running=False; state.emergency_stopped=True; state.updated_at=datetime.now(timezone.utc)
    return {"ok":True,"message":"New trading disabled and bot stopped","state":get_bot()}
@app.post("/v1/bot/reset-emergency")
def reset_emergency(): state.emergency_stopped=False; state.updated_at=datetime.now(timezone.utc); return get_bot()
@app.put("/v1/bot/risk")
def update_risk(settings:RiskSettings): state.risk=settings; state.updated_at=datetime.now(timezone.utc); return get_bot()
