import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field
from .auth import current_user
from .auth_api import router as auth_router
from .notifications_api import router as notifications_router, send_push, notification_event
from .bridge_api import router as bridge_router
from .bridge_sync_api import router as bridge_sync_router
from .db import connection
from .market_data import candles_for, latest_price
from .strategy import analyze_multi_timeframe, backtest_strategy
from .risk_api import approve_trade
from .trade_api import router as trade_router, queue_bridge_command, mt5_connected
from .validation_api import router as validation_router
from .journal_api import router as journal_router
from .trade_manager import mark_prices, list_positions, open_paper_position
from .account_sync import live_account_metrics

MARKETS=[
    "EURUSD","GBPUSD","USDJPY","USDCHF","AUDUSD","USDCAD","NZDUSD",
    "XAUUSD","XAGUSD","BTCUSD","ETHUSD","NAS100","US30","SPX500",
]

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

def ai_auto_approval_settings(user_id):
    with connection() as conn:
        row=conn.execute(
            "SELECT payload FROM audit_events WHERE user_id=%s AND event_type='ai_auto_approval_setting' ORDER BY created_at DESC LIMIT 1",
            (user_id,)
        ).fetchone()
    payload=row[0] if row else {}
    return {"enabled":bool(payload.get("enabled",False)),"min_score":float(payload.get("min_score",80)),"demo_only":True}

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
                    signal=await multi_timeframe_analysis(symbol,str(user_id))
                    if signal.get("signal") not in ("BUY","SELL"):
                        continue
                    signal_symbol=signal.get("symbol",symbol.replace("USDT","/USD"))
                    if recent_signal_exists(user_id,signal_symbol,signal.get("signal")):
                        continue
                    account=live_account_metrics(str(user_id))
                    with connection() as conn:
                        risk=conn.execute("SELECT risk_per_trade,daily_loss_limit,max_open_trades,max_drawdown FROM bot_state WHERE user_id=%s",(user_id,)).fetchone()
                    if not account or not risk:
                        continue
                    decision=approve_trade(
                        signal,
                        balance=float(account["balance"]),
                        equity=float(account["equity"]),
                        today_pnl_percent=(float(account["today_pl"])/max(float(account["balance"]),1))*100,
                        drawdown_percent=float(account["drawdown"]),
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
                    send_push(user_id,f"{signal.get('signal')} signal · {signal.get('symbol',symbol)}",str(signal.get("reason") or "Trade signal detected"),{"type":"signal","symbol":signal.get("symbol",symbol),"action":signal.get("signal")})
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

async def multi_timeframe_analysis(symbol,user_id):
    """Build one setup from 1H regime, 15M structure, and 5M entry trigger."""
    candles_1h,candles_15m,candles_5m=await asyncio.gather(
        candles_for(symbol,interval="1h",limit=220,user_id=user_id),
        candles_for(symbol,interval="15m",limit=220,user_id=user_id),
        candles_for(symbol,interval="5m",limit=220,user_id=user_id),
    )
    return analyze_multi_timeframe(candles_1h,candles_15m,candles_5m)

async def market_alert_cycle():
    """
    Continuously scan MT5 markets. Normal mode sends alerts. When the user
    explicitly enables AI Auto-Approval, a high-confidence risk-approved
    signal can be queued for MT5 demo execution while the user is away.
    """
    try:
        with connection() as conn:
            users=conn.execute("SELECT DISTINCT user_id FROM bridge_pairings").fetchall()
        for (user_id,) in users:
            user_id=str(user_id)
            settings=ai_auto_approval_settings(user_id)
            for symbol in MARKETS:
                try:
                    signal=await multi_timeframe_analysis(symbol,user_id)
                    action=signal.get("signal")
                    score=float(signal.get("score") or 0)
                    if action not in ("BUY","SELL") or score < 70:
                        continue
                    signal_symbol=signal.get("symbol",symbol)
                    if recent_signal_exists(user_id,signal_symbol,action,minutes=15):
                        continue

                    account=live_account_metrics(user_id)
                    with connection() as conn:
                        risk=conn.execute(
                            "SELECT risk_per_trade,daily_loss_limit,max_open_trades,max_drawdown FROM bot_state WHERE user_id=%s",
                            (user_id,)
                        ).fetchone()
                    if not account or not risk:
                        continue

                    open_now=list_positions("open",user_id)
                    if any(p.symbol == signal_symbol.replace("USDT","/USD") for p in open_now):
                        continue

                    decision=approve_trade(
                        signal,
                        balance=float(account["balance"]),
                        equity=float(account["equity"]),
                        today_pnl_percent=(float(account["today_pl"])/max(float(account["balance"]),1))*100,
                        drawdown_percent=float(account["drawdown"]),
                        open_trades=len(open_now),
                        risk_per_trade=float(risk[0]),
                        daily_loss_limit=float(risk[1]),
                        max_open_trades=int(risk[2]),
                        max_drawdown=float(risk[3]),
                    )

                    payload={
                        "symbol":signal_symbol,
                        "action":action,
                        "score":score,
                        "confidence":score,
                        "entry":signal.get("entry"),
                        "stop_loss":signal.get("stop_loss"),
                        "take_profit":signal.get("take_profit"),
                        "reason":signal.get("reason"),
                        "source":"MT5",
                        "timeframe":"MTF","entry_trigger":signal.get("entry_trigger"),"timeframes":signal.get("timeframes"),
                        "risk_approved":bool(decision.get("approved")),
                    }

                    with connection() as conn:
                        conn.execute(
                            "INSERT INTO signals (user_id,symbol,action,score,reason,entry,stop_loss,take_profit) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                            (user_id,signal_symbol,action,score,signal.get("reason"),signal.get("entry"),signal.get("stop_loss"),signal.get("take_profit"))
                        )
                    notification_event(user_id,"notification_signal",payload)

                    auto_approved=False
                    command_id=None
                    if settings["enabled"] and score >= settings["min_score"] and decision.get("approved") and mt5_connected(user_id):
                        command_id=queue_bridge_command(
                            user_id,
                            "open_market",
                            {
                                "symbol":signal.get("mt5_symbol") or str(signal_symbol).replace("/",""),
                                "side":action,
                                "volume":float(decision["quantity"]),
                                "stop_loss":signal.get("stop_loss"),
                                "take_profit":signal.get("take_profit"),
                                "reason":"TradeGuard AI Auto-Approval",
                            }
                        )
                        auto_approved=True

                    if auto_approved:
                        notification_event(user_id,"notification_trade_approval_needed",
                            {**payload,"ai_approved":True,"command_id":command_id,"execution":"MT5_DEMO"})
                        send_push(
                            user_id,
                            f"AI APPROVED · {action} {signal_symbol}",
                            f"AI approved {action} · score {int(score)} · entry {signal.get('entry')} · MT5 demo execution queued.",
                            {"type":"ai_trade_approved","command_id":command_id,**payload},
                        )
                    else:
                        send_push(
                            user_id,
                            f"{action} setup · {signal_symbol}",
                            f"Confirmed {action} setup · score {int(score)} · entry {signal.get('entry')} · 1H {signal.get('timeframes',{}).get('1h','—')} · 15M {signal.get('timeframes',{}).get('15m','—')} · 5M trigger {signal.get('entry_trigger','waiting')}",
                            {"type":"market_signal",**payload},
                        )
                except Exception:
                    continue
    except Exception:
        pass

async def trading_worker():
    while True:
        await auto_trade_cycle()
        await asyncio.sleep(60)

async def market_alert_worker():
    while True:
        await market_alert_cycle()
        await asyncio.sleep(60)

@asynccontextmanager
async def lifespan(app):
    price_task=asyncio.create_task(price_monitor())
    trade_task=asyncio.create_task(trading_worker())
    alert_task=asyncio.create_task(market_alert_worker())
    yield
    price_task.cancel()
    trade_task.cancel()
    alert_task.cancel()

app=FastAPI(title="TradeGuard API",version="0.6.0",lifespan=lifespan)
app.include_router(auth_router)
app.include_router(notifications_router)
app.include_router(bridge_router)
app.include_router(bridge_sync_router)
app.include_router(trade_router)
app.include_router(validation_router)
app.include_router(journal_router)

@app.get("/v1/strategy/backtest")
async def strategy_backtest(
    symbol: str = "EURUSD",
    interval: str = "15m",
    limit: int = 800,
    user=Depends(current_user),
):
    """Run a non-executing walk-forward validation of the current candle strategy."""
    allowed_intervals={"5m","15m","1h"}
    if interval not in allowed_intervals:
        raise HTTPException(400,"Interval must be 5m, 15m, or 1h")
    limit=max(250,min(int(limit),1200))
    try:
        candles=await candles_for(symbol.upper(),interval=interval,limit=limit,user_id=user["id"])
        # Avoid treating the currently forming external candle as historical data.
        if len(candles)>1 and candles[-1].time is not None:
            candles=candles[:-1]
        report=backtest_strategy(candles,warmup=200,horizon=24)
        return {
            "symbol":symbol.upper(),
            "interval":interval,
            "engine":"TradeGuard candle strategy v1",
            "lookahead_safe":True,
            "execution":False,
            **report,
        }
    except Exception as exc:
        raise HTTPException(503,f"Backtest data unavailable: {exc}")

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

class AIAutoApprovalSettings(BaseModel):
    enabled:bool=False
    min_score:float=Field(80,ge=70,le=100)

@app.get("/v1/bot/ai-approval")
def get_ai_approval(user=Depends(current_user)):
    return ai_auto_approval_settings(user["id"])

@app.put("/v1/bot/ai-approval")
def update_ai_approval(settings:AIAutoApprovalSettings,user=Depends(current_user)):
    with connection() as conn:
        conn.execute(
            "INSERT INTO audit_events (user_id,event_type,payload) VALUES (%s,'ai_auto_approval_setting',%s::jsonb)",
            (user["id"],__import__("json").dumps({"enabled":settings.enabled,"min_score":settings.min_score,"demo_only":True}))
        )
    return ai_auto_approval_settings(user["id"])

@app.get("/health")
def health(): return {"ok":True,"service":"tradeguard-api","time":datetime.now(timezone.utc)}

@app.get("/v1/account")
def account(user=Depends(current_user)):
    with connection() as conn:
        bot=conn.execute("SELECT running,risk_per_trade,daily_loss_limit,max_open_trades,max_drawdown FROM bot_state WHERE user_id=%s",(user["id"],)).fetchone()
        open_count=conn.execute("SELECT COUNT(*) FROM positions WHERE user_id=%s AND status='open'",(user["id"],)).fetchone()[0]
    account=live_account_metrics(user["id"])
    if not account or not bot: raise HTTPException(500,"Account state is not initialized")

    return {
        "balance":account["balance"],
        "equity":account["equity"],
        "today_pl":account["today_pl"],
        "drawdown":account["drawdown"],
        "currency":account["currency"],
        "bot":{
            "running":bool(bot[0]),
            "risk_per_trade":float(bot[1]),
            "daily_loss_limit":float(bot[2]),
            "max_open_trades":int(bot[3]),
            "max_drawdown":float(bot[4]),
            "open_trades":int(open_count)
        }
    }

@app.get("/v1/markets")
async def get_markets(user=Depends(current_user)):
    results=[]
    for symbol in MARKETS:
        try:
            result=await multi_timeframe_analysis(symbol,user["id"])
            # The scanner must show every successfully analyzed market.
            # NO TRADE and WATCH are valid strategy outcomes and should remain
            # visible instead of making the Markets screen appear empty.
            results.append({"symbol":symbol.replace("USDT","/USD"),**result})
        except Exception as exc:
            # Keep one failed feed from hiding the rest of the scanner.
            results.append({
                "symbol":symbol.replace("USDT","/USD"),
                "signal":"NO TRADE",
                "score":0,
                "reason":"Market data temporarily unavailable",
            })
    results.sort(key=lambda row: float(row.get("score") or 0), reverse=True)
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
def update_mode(settings: ModeSettings,user=Depends(current_user)):
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
