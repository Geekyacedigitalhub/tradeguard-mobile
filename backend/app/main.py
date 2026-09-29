from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from datetime import datetime, timezone

app = FastAPI(title="TradeGuard API", version="0.1.0")

class RiskSettings(BaseModel):
    risk_per_trade: float = Field(0.5, ge=0.1, le=5)
    daily_loss_limit: float = Field(2.0, ge=0.5, le=20)
    max_open_trades: int = Field(3, ge=1, le=20)
    max_drawdown: float = Field(5.0, ge=1, le=50)

class BotState(BaseModel):
    running: bool = False
    emergency_stopped: bool = False
    mode: str = "semi_auto"
    risk: RiskSettings = RiskSettings()
    updated_at: datetime = datetime.now(timezone.utc)

state = BotState()

markets = [
    {"symbol":"EUR/USD","score":88,"signal":"BUY","reason":"Bullish trend + momentum + structure","entry":1.17240,"stop_loss":1.17140,"take_profit":1.17440},
    {"symbol":"GBP/USD","score":64,"signal":"NO TRADE","reason":"Trend conflict","entry":None,"stop_loss":None,"take_profit":None},
    {"symbol":"XAU/USD","score":57,"signal":"NO TRADE","reason":"Volatility outside configured range","entry":None,"stop_loss":None,"take_profit":None},
    {"symbol":"BTC/USD","score":71,"signal":"WATCH","reason":"Setup developing","entry":None,"stop_loss":None,"take_profit":None},
]

@app.get("/health")
def health():
    return {"ok": True, "service": "tradeguard-api", "time": datetime.now(timezone.utc)}

@app.get("/v1/account")
def account():
    return {"balance":1000.0,"equity":1024.20,"today_pnl":24.20,"drawdown":1.2,"currency":"USD"}

@app.get("/v1/markets")
def get_markets():
    return {"markets": markets}

@app.get("/v1/signals")
def get_signals():
    return {"signals":[m for m in markets if m["signal"] in ("BUY","SELL")]}

@app.get("/v1/bot")
def get_bot():
    return state.model_dump()

@app.post("/v1/bot/start")
def start_bot():
    if state.emergency_stopped:
        raise HTTPException(409, "Emergency stop is active. Reset it before starting the bot.")
    state.running=True
    state.updated_at=datetime.now(timezone.utc)
    return state.model_dump()

@app.post("/v1/bot/stop")
def stop_bot():
    state.running=False
    state.updated_at=datetime.now(timezone.utc)
    return state.model_dump()

@app.post("/v1/bot/emergency-stop")
def emergency_stop():
    state.running=False
    state.emergency_stopped=True
    state.updated_at=datetime.now(timezone.utc)
    return {"ok":True,"message":"New trading disabled and bot stopped","state":state.model_dump()}

@app.post("/v1/bot/reset-emergency")
def reset_emergency():
    state.emergency_stopped=False
    state.updated_at=datetime.now(timezone.utc)
    return state.model_dump()

@app.put("/v1/bot/risk")
def update_risk(settings: RiskSettings):
    state.risk=settings
    state.updated_at=datetime.now(timezone.utc)
    return state.model_dump()
