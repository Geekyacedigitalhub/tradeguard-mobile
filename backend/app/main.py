import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket
from pydantic import BaseModel, Field
from .auth import _decode_token, current_user
from .auth_api import router as auth_router
from .notifications_api import router as notifications_router, send_push, notification_event
from .ctrader_oauth_api import router as ctrader_oauth_router
from .bridge_sync_api import router as bridge_sync_router
from .db import connection, ensure_schema
from .market_data import candles_for, latest_price, sync_cloud_market_data
from .strategy import analyze_multi_timeframe, backtest_strategy
from .risk_api import approve_trade
from .risk_metrics import consecutive_losses
from .intelligence import market_intelligence
from .technical_engine import deep_market_analysis
from .validation_gate import latest_validation_gate
from .profit_engine import evaluate_opportunity, rank_opportunities
from .learning import learning_gate
from .optimizer import optimizer_gate
from .trade_api import router as trade_router, queue_bridge_command, ctrader_connected
from .execution import execution_provider, execution_snapshot
from .ctrader_service import manager as ctrader_manager
from .ctrader_worker import ctrader_command_worker
from .validation_api import router as validation_router
from .journal_api import router as journal_router
from .trade_manager import mark_prices, list_positions
from .account_sync import live_account_metrics

MARKETS=[
    "EURUSD","GBPUSD","USDJPY","USDCHF","AUDUSD","USDCAD","NZDUSD",
    "XAUUSD","XAGUSD","BTCUSD","ETHUSD","NAS100","US30","SPX500",
]

# Short-lived process-local cache keeps repeated cloud market scans responsive.
_market_cache={}
MARKET_CACHE_TTL=60
_market_scan_tasks={}
# Share expensive MTF analysis between background workers and API scans.
_ANALYSIS_CACHE={}
_ANALYSIS_CACHE_TTL=45
_ANALYSIS_TASKS={}
_risk_cache={}
_RISK_CACHE_TTL=10
_ai_approval_cache={}
_AI_APPROVAL_CACHE_TTL=30
_account_route_cache={}
_ACCOUNT_ROUTE_CACHE_TTL=10
_broker_status_cache={}
_BROKER_STATUS_CACHE_TTL=5
_bot_state_cache={}
_BOT_STATE_CACHE_TTL=5


async def ctrader_heartbeat_worker():
    while True:
        try:
            ctrader_manager.heartbeat_snapshot()
        except Exception:
            pass
        await asyncio.sleep(10)

async def price_monitor():
    while True:
        try:
            open_positions=list_positions("open")
            symbols={p.symbol.replace("/USD","USDT") for p in open_positions}
            if symbols:
                prices={}
                for symbol in symbols:
                    try: prices[symbol]=await latest_price(symbol)
                    except Exception: pass
                mark_prices(prices,open_positions)
        except Exception:
            pass
        await asyncio.sleep(15)

def ai_auto_approval_settings(user_id):
    user_id=str(user_id)
    import time
    cached=_ai_approval_cache.get(user_id)
    now=time.monotonic()
    if cached and now-cached[0] < _AI_APPROVAL_CACHE_TTL:
        return cached[1]
    with connection() as conn:
        row=conn.execute(
            "SELECT payload FROM audit_events WHERE user_id=%s AND event_type='ai_auto_approval_setting' ORDER BY created_at DESC LIMIT 1",
            (user_id,)
        ).fetchone()
    payload=row[0] if row else {}
    result={"enabled":bool(payload.get("enabled",False)),"min_score":float(payload.get("min_score",80)),"demo_only":True}
    _ai_approval_cache[user_id]=(now,result)
    return result

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
                    if signal.get("deep_analysis",{}).get("decision")!="TRADE CANDIDATE":
                        continue
                    if signal.get("profit_engine",{}).get("decision")!="EXECUTE":
                        continue
                    signal_symbol=signal.get("symbol",symbol.replace("USDT","/USD"))
                    if recent_signal_exists(user_id,signal_symbol,signal.get("signal")):
                        continue
                    account=live_account_metrics(str(user_id))
                    cached_risk=_risk_cache.get(str(user_id))
                    if cached_risk and asyncio.get_running_loop().time()-cached_risk[0] < _RISK_CACHE_TTL:
                        risk=cached_risk[1]
                    else:
                        with connection() as conn:
                            risk=conn.execute("SELECT risk_per_trade,daily_loss_limit,max_open_trades,max_drawdown FROM bot_state WHERE user_id=%s",(user_id,)).fetchone()
                        if risk:
                            _risk_cache[str(user_id)]=(asyncio.get_running_loop().time(),risk)
                    loss_streak=consecutive_losses(str(user_id))
                    if not account or not risk:
                        continue
                    decision=approve_trade(
                        signal,
                        balance=float(account["balance"]),
                        equity=float(account["equity"]),
                        today_pnl_percent=(float(account["today_pl"])/max(float(account["balance"]),1))*100,
                        drawdown_percent=float(account["drawdown"]),
                        open_trades=len(open_now),
                        consecutive_losses=loss_streak,
                        risk_per_trade=float(risk[0]) * float(signal.get("profit_engine",{}).get("risk_multiplier",1.0)),
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
                        # Automated broker execution is disabled; fail closed until
                        # cTrader-only safety checks have passed end to end.
                        provider=execution_provider(str(user_id))
                        if provider=="none":
                            notification_event(user_id,"notification_trade_execution_blocked",{
                                "symbol":signal_symbol,
                                "action":signal.get("signal"),
                                "reason":"Cloud execution node is offline; trade was blocked.",
                            })
                            continue
                        if provider!="ctrader":
                            notification_event(user_id,"notification_trade_execution_blocked",{
                                "symbol":signal_symbol,
                                "action":signal.get("signal"),
                                "reason":"cTrader automated entries remain disabled until execution safety checks pass. No order was sent.",
                            })
                            continue
                        notification_event(user_id,"notification_trade_execution_blocked",{
                            "symbol":signal_symbol,
                            "action":signal.get("signal"),
                            "reason":"cTrader automated entries remain disabled until verified broker-volume sizing, selected demo-account validation, fresh-quote checks, and mandatory SL/TP protection pass end-to-end tests.",
                        })
                        continue
                    elif mode=="semi_auto":
                        notification_event(user_id,"notification_trade_approval_needed",{"symbol":signal.get("symbol",symbol),"action":signal.get("signal"),"quantity":decision.get("quantity"),"reason":"Risk checks passed; manual approval required"})
                except Exception:
                    continue
    except Exception:
        pass

async def multi_timeframe_analysis(symbol,user_id):
    """Build one setup from 1H regime, 15M structure, and 5M entry trigger."""
    symbol=symbol.upper()
    user_id=str(user_id)
    cache_key=(user_id,symbol)
    now=__import__("time").monotonic()
    cached=_ANALYSIS_CACHE.get(cache_key)
    if cached and now-cached["time"] < _ANALYSIS_CACHE_TTL:
        return cached["result"]

    task=_ANALYSIS_TASKS.get(cache_key)
    if task is None:
        async def run_analysis():
            candles_1h,candles_15m,candles_5m=await asyncio.gather(
                candles_for(symbol,interval="1h",limit=220,user_id=user_id),
                candles_for(symbol,interval="15m",limit=220,user_id=user_id),
                candles_for(symbol,interval="5m",limit=220,user_id=user_id),
            )
            signal=analyze_multi_timeframe(candles_1h,candles_15m,candles_5m)
            raw_signal=signal.get("signal")
            signal["deep_analysis"]=deep_market_analysis(candles_1h,candles_15m,candles_5m)
            signal["intelligence"]=market_intelligence(signal,candles_5m,signal["deep_analysis"])

            historical=latest_validation_gate(user_id,symbol)
            signal["profit_engine"]=evaluate_opportunity(signal,historical=historical)
            learning=learning_gate(
                user_id,symbol,
                setup="TradeGuard MTF Price Action v2",
                session=(signal.get("intelligence") or {}).get("session"),
                regime=(signal.get("intelligence") or {}).get("regime"),
            )
            optimizer=optimizer_gate(
                user_id,symbol,
                setup="TradeGuard MTF Price Action v2",
                session=(signal.get("intelligence") or {}).get("session"),
                regime=(signal.get("intelligence") or {}).get("regime"),
            )
            signal["profit_engine"]["learning"]=learning
            signal["profit_engine"]["optimizer"]=optimizer
            signal["profit_engine"]["risk_multiplier"]=round(
                float(signal["profit_engine"].get("risk_multiplier") or 1.0)
                * float(learning.get("modifier") or 1.0)
                * float(optimizer.get("modifier") or 1.0),3
            )
            if not learning.get("approved") or not optimizer.get("approved"):
                signal["profit_engine"]["decision"]="WAIT"
                signal["profit_engine"]["tier"]="REJECT"
                signal["profit_engine"].setdefault("vetoes",[]).append(learning.get("reason") or "Live learning gate rejected the setup.")
            signal["historical_gate"]=historical

            # The deep research and profit gates are authoritative for execution-facing signals.
            # Keep the original MTF result visible as raw_signal, but never expose a
            # BUY/SELL setup as executable when deeper research rejects it.
            deep_decision=signal["deep_analysis"].get("decision")
            signal["raw_signal"]=raw_signal
            profit_decision=signal["profit_engine"].get("decision")
            signal["trade_candidate"]=deep_decision=="TRADE CANDIDATE" and profit_decision=="EXECUTE"
            if raw_signal in ("BUY","SELL") and not signal["trade_candidate"]:
                signal["signal"]="WATCH"
                signal["reason"]=(
                    f"Deep research gate rejected execution · {signal['deep_analysis'].get('summary') or deep_decision or 'NO TRADE'}"
                )
            return signal

        task=asyncio.create_task(run_analysis())
        _ANALYSIS_TASKS[cache_key]=task

    try:
        result=await task
        _ANALYSIS_CACHE[cache_key]={"time":__import__("time").monotonic(),"result":result}
        return result
    finally:
        if _ANALYSIS_TASKS.get(cache_key) is task:
            _ANALYSIS_TASKS.pop(cache_key,None)

async def market_alert_cycle():
    """
    Continuously scan cloud markets. Normal mode sends alerts. When the user
    explicitly enables AI Auto-Approval, a high-confidence risk-approved
    signal can be queued for demo execution while the user is away.
    """
    try:
        with connection() as conn:
            users=conn.execute("SELECT user_id FROM ctrader_connections WHERE account_id IS NOT NULL AND LOWER(COALESCE(environment,'demo'))='demo'").fetchall()
        for (user_id,) in users:
            user_id=str(user_id)
            settings=ai_auto_approval_settings(user_id)
            open_now=list_positions("open",user_id)
            loss_streak=consecutive_losses(user_id)
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
                    cached_risk=_risk_cache.get(user_id)
                    if cached_risk and asyncio.get_running_loop().time()-cached_risk[0] < _RISK_CACHE_TTL:
                        risk=cached_risk[1]
                    else:
                        with connection() as conn:
                            risk=conn.execute(
                                "SELECT risk_per_trade,daily_loss_limit,max_open_trades,max_drawdown FROM bot_state WHERE user_id=%s",
                                (user_id,)
                            ).fetchone()
                        if risk:
                            _risk_cache[user_id]=(asyncio.get_running_loop().time(),risk)
                    risk_metrics_available=bool(account and risk)
                    if any(p.symbol == signal_symbol.replace("USDT","/USD") for p in open_now):
                        continue

                    if risk_metrics_available:
                        decision=approve_trade(
                            signal,
                            balance=float(account["balance"]),
                            equity=float(account["equity"]),
                            today_pnl_percent=(float(account["today_pl"])/max(float(account["balance"]),1))*100,
                            drawdown_percent=float(account["drawdown"]),
                            open_trades=len(open_now),
                            consecutive_losses=loss_streak,
                            risk_per_trade=float(risk[0]),
                            daily_loss_limit=float(risk[1]),
                            max_open_trades=int(risk[2]),
                            max_drawdown=float(risk[3]),
                        )
                    else:
                        decision={"approved":False,"reason":"Verified cTrader risk metrics unavailable"}

                    historical_gate=latest_validation_gate(user_id,signal_symbol)
                    deep_gate=signal.get("deep_analysis",{}).get("decision")=="TRADE CANDIDATE"
                    profit_gate=signal.get("profit_engine",{}).get("decision")=="EXECUTE"
                    payload={
                        "symbol":signal_symbol,
                        "action":action,
                        "score":score,
                        "confidence":score,
                        "entry":signal.get("entry"),
                        "stop_loss":signal.get("stop_loss"),
                        "take_profit":signal.get("take_profit"),
                        "reason":signal.get("reason"),
                        "source":"CLOUD",
                        "timeframe":"MTF","entry_trigger":signal.get("entry_trigger"),"timeframes":signal.get("timeframes"),
                        "risk_approved":bool(decision.get("approved")),
                        "risk_metrics_available":risk_metrics_available,
                        "risk_reason":None if risk_metrics_available else "Verified cTrader balance, equity, daily P/L, and drawdown are unavailable; no risk approval or order is permitted.",
                        "historical_gate":historical_gate,
                        "deep_research_gate":deep_gate,
                    }

                    with connection() as conn:
                        conn.execute(
                            "INSERT INTO signals (user_id,symbol,action,score,reason,entry,stop_loss,take_profit) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                            (user_id,signal_symbol,action,score,signal.get("reason"),signal.get("entry"),signal.get("stop_loss"),signal.get("take_profit"))
                        )
                    notification_event(user_id,"notification_signal",payload)

                    # Automated broker execution is disabled. Keep signal
                    # alerts active, but never queue broker writes from this path.
                    if settings["enabled"] and score >= settings["min_score"] and not risk_metrics_available:
                        notification_event(
                            user_id,
                            "notification_trade_execution_blocked",
                            {
                                **payload,
                                "reason": "Risk approval was skipped because verified cTrader account metrics are unavailable. No order was sent.",
                            },
                        )
                    elif (
                        settings["enabled"]
                        and score >= settings["min_score"]
                        and decision.get("approved")
                        and historical_gate.get("approved")
                        and deep_gate
                        and profit_gate
                    ):
                        notification_event(
                            user_id,
                            "notification_trade_execution_blocked",
                            {
                                **payload,
                                "reason": "Automated execution is disabled until the cTrader-only pipeline has verified broker-volume sizing, selected demo-account validation, fresh-quote checks, and mandatory SL/TP protection.",
                            },
                        )

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
    ensure_schema()
    price_task=asyncio.create_task(price_monitor())
    trade_task=asyncio.create_task(trading_worker())
    alert_task=asyncio.create_task(market_alert_worker())
    ctrader_manager.start()
    await ctrader_manager.restore_from_db()
    ctrader_heartbeat_task=asyncio.create_task(ctrader_heartbeat_worker())
    ctrader_command_task=asyncio.create_task(ctrader_command_worker())
    yield
    price_task.cancel()
    trade_task.cancel()
    alert_task.cancel()
    ctrader_heartbeat_task.cancel()
    ctrader_command_task.cancel()
    ctrader_manager.stop()

app=FastAPI(title="TradeGuard API",version="0.6.0",lifespan=lifespan)
app.include_router(auth_router)
app.include_router(notifications_router)
app.include_router(ctrader_oauth_router)
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
    import time
    cache_key=str(user["id"])
    now=time.monotonic()
    cached=_broker_status_cache.get(cache_key)
    if cached and now-cached[0] < _BROKER_STATUS_CACHE_TTL:
        return cached[1]
    with connection() as conn:
        row=conn.execute(
            """SELECT ae.payload,ae.created_at,ast.updated_at
               FROM audit_events ae
               LEFT JOIN account_state ast ON ast.user_id=ae.user_id
               WHERE ae.user_id=%s AND ae.event_type='broker_connection'
               ORDER BY ae.created_at DESC LIMIT 1""",
            (user["id"],)
        ).fetchone()
    if not row:
        result={
            "connected":False,
            "stale":True,
            "provider":"ctrader_cloud",
            "terminal":"cTrader Cloud",
            "environment":"demo",
            "message":"cTrader is not connected. Authorize cTrader and select a demo account.",
        }
        _broker_status_cache[cache_key]=(now,result)
        return result
    payload=row[0] or {}
    # cTrader writes a fresh broker_connection audit event every 10 seconds.
    # account_state.updated_at belongs to the retired EA flow, so ignore it here.
    last_seen=row[1]
    stale=not last_seen or (datetime.now(timezone.utc)-last_seen).total_seconds()>45
    is_ctrader=payload.get("terminal")=="cTrader Cloud" and payload.get("provider")=="cTrader"
    connected=bool(payload.get("connected",False)) and not stale and is_ctrader
    result={
        "connected":connected,
        "stale":stale,
        "last_seen":last_seen,
        "provider":"ctrader_cloud",
        "terminal":"cTrader Cloud",
        "environment":payload.get("environment","demo"),
        "account":payload.get("account") if is_ctrader else None,
        "message":(
            "cTrader cloud heartbeat is stale."
            if stale
            else "cTrader is not connected. Authorize cTrader and select a demo account."
            if not is_ctrader
            else "cTrader Cloud is connected."
        ),
    }
    _broker_status_cache[cache_key]=(now,result)
    return result

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
    _ai_approval_cache.pop(str(user["id"]),None)
    return ai_auto_approval_settings(user["id"])

@app.api_route("/v1/internal/cloud-market-sync", methods=["GET","POST"])
async def cloud_market_sync(request: Request, token: str | None = None):
    expected=os.getenv("TRADEGUARD_CRON_SECRET","").strip()
    supplied=request.headers.get("x-tradeguard-cron","").strip() or (token or "").strip()
    if not expected or not supplied or supplied != expected:
        raise HTTPException(403,"Invalid cloud sync credentials")
    report = await sync_cloud_market_data()
    print(f"CLOUD_SYNC updated={report.get("updated", 0)} failed={report.get("failed", 0)} time={report.get("time", "")}", flush=True)
    return {"ok": report.get("failed", 0) == 0, "updated": report.get("updated", 0), "failed": report.get("failed", 0), "time": report.get("time")}


@app.post("/v1/internal/live-ticks")
async def live_ticks():
    raise HTTPException(
        410,
        "The legacy terminal tick bridge is disabled. cTrader live-tick streaming is not yet enabled.",
    )

@app.websocket("/v1/market-stream")
async def market_stream(websocket:WebSocket):
    await websocket.close(
        code=1013,
        reason="cTrader live-tick streaming is not enabled yet",
    )

@app.get("/health")
def health(): return {"ok":True,"service":"tradeguard-api","time":datetime.now(timezone.utc)}

@app.get("/v1/account")
def account(user=Depends(current_user)):
    import time
    cache_key=str(user["id"])
    cached=_account_route_cache.get(cache_key)
    now=time.monotonic()
    if cached and now-cached[0] < _ACCOUNT_ROUTE_CACHE_TTL:
        return cached[1]
    with connection() as conn:
        bot=conn.execute("""
            SELECT b.running,b.risk_per_trade,b.daily_loss_limit,b.max_open_trades,b.max_drawdown
            FROM bot_state b
            WHERE b.user_id=%s
        """,(user["id"],)).fetchone()
    account=live_account_metrics(user["id"])
    broker_positions=None
    if ctrader_connected(user["id"]):
        with connection() as conn:
            row=conn.execute(
                "SELECT payload FROM audit_events WHERE user_id=%s AND event_type='broker_connection' ORDER BY created_at DESC LIMIT 1",
                (user["id"],)
            ).fetchone()
        payload=row[0] if row else {}
        broker_positions=payload.get("positions") if isinstance(payload.get("positions"),list) else None
    open_count=len(broker_positions) if broker_positions is not None else len(list_positions("open",user["id"]))
    if not bot: raise HTTPException(500,"Bot settings are not initialized")

    result={
        "balance":account["balance"] if account else None,
        "equity":account["equity"] if account else None,
        "today_pl":account["today_pl"] if account else None,
        "drawdown":account["drawdown"] if account else None,
        "currency":account["currency"] if account else None,
        "account_metrics_available":bool(account),
        "account_metrics_message":None if account else "Fresh cTrader balance, equity, daily P/L, and drawdown are not all verified yet; risk-based execution remains blocked.",
        "bot":{
            "running":bool(bot[0]),
            "risk_per_trade":float(bot[1]),
            "daily_loss_limit":float(bot[2]),
            "max_open_trades":int(bot[3]),
            "max_drawdown":float(bot[4]),
            "open_trades":int(open_count)
        }
    }
    _account_route_cache[cache_key]=(now,result)
    return result

@app.get("/v1/markets/{symbol}/candles")
async def market_candles(
    symbol: str,
    interval: str = "5m",
    limit: int = 120,
    user=Depends(current_user),
):
    allowed_intervals={"5m","15m","1h"}
    if interval not in allowed_intervals:
        raise HTTPException(400,"Interval must be 5m, 15m, or 1h")
    symbol=symbol.upper()
    if symbol not in MARKETS:
        raise HTTPException(400,"Unsupported market symbol")
    limit=max(50,min(int(limit),300))
    try:
        candles=await candles_for(symbol,interval=interval,limit=limit,user_id=user["id"])
        return {
            "symbol":symbol,
            "interval":interval,
            "candles":[
                {"time":c.time,"open":c.open,"high":c.high,"low":c.low,"close":c.close,"volume":c.volume}
                for c in candles
            ],
        }
    except Exception as exc:
        raise HTTPException(503,f"Market chart data unavailable: {exc}")

@app.get("/v1/markets")
async def get_markets(user=Depends(current_user)):
    user_id=str(user["id"])
    cache_key=user_id
    cached=_market_cache.get(cache_key)
    now=__import__("time").monotonic()
    if cached and now-cached["time"] < MARKET_CACHE_TTL:
        return cached["results"]

    # Only one expensive scan may run for a user at a time. The Home and
    # Markets screens both poll the same endpoint, so duplicate scans waste
    # the small Render instance and can make the phone see network failures.
    task=_market_scan_tasks.get(cache_key)
    if task is None:
        async def run_scan():
            semaphore=asyncio.Semaphore(3)

            async def analyze_one(symbol):
                async with semaphore:
                    try:
                        result=await asyncio.wait_for(
                            multi_timeframe_analysis(symbol,user_id),
                            timeout=12,
                        )
                        return {"symbol":symbol.replace("USDT","/USD"),**result}
                    except Exception as exc:
                        print(f"MARKET_SCAN_ERROR {symbol}: {str(exc)[:180]}", flush=True)
                        previous={}
                        if cached:
                            previous=next((r for r in cached["results"] if r.get("symbol")==symbol.replace("USDT","/USD")), {})
                        if previous and previous.get("signal") in ("BUY","SELL"):
                            return previous
                        return {
                            "symbol":symbol.replace("USDT","/USD"),
                            "signal":"NO TRADE",
                            "score":0,
                            "reason":"Market data temporarily unavailable",
                        }

            results=await asyncio.gather(*(analyze_one(symbol) for symbol in MARKETS))
            results=rank_opportunities(results)
            for index,row in enumerate(results,1):
                row["opportunity_rank"]=index
            _market_cache[cache_key]={"time":__import__("time").monotonic(),"results":results}
            return results

        task=asyncio.create_task(run_scan())
        _market_scan_tasks[cache_key]=task

    try:
        return await task
    finally:
        if _market_scan_tasks.get(cache_key) is task:
            _market_scan_tasks.pop(cache_key,None)

@app.post("/v1/risk/check")
def risk_check(signal:dict,user=Depends(current_user)):
    # Never approve from the retired terminal/EA account_state table.
    # Only fresh, account-matched cTrader Cloud demo metrics may drive risk checks.
    account=live_account_metrics(user["id"])
    with connection() as conn:
        row=conn.execute("""
            SELECT risk_per_trade,daily_loss_limit,max_open_trades,max_drawdown
            FROM bot_state
            WHERE user_id=%s
        """,(user["id"],)).fetchone()
    if not row:
        raise HTTPException(500,"Risk settings are not initialized")
    if not account:
        return {
            "approved":False,
            "reason":"Verified fresh cTrader demo balance, equity, daily P/L, and drawdown are unavailable.",
            "risk_metrics_available":False,
            "execution":"locked",
        }
    decision=approve_trade(
        signal,
        balance=float(account["balance"]),
        equity=float(account["equity"]),
        today_pnl_percent=(float(account["today_pl"])/max(float(account["balance"]),1))*100,
        drawdown_percent=float(account["drawdown"]),
        consecutive_losses=consecutive_losses(user["id"]),
        risk_per_trade=float(row[0]),
        daily_loss_limit=float(row[1]),
        max_open_trades=int(row[2]),
        max_drawdown=float(row[3]),
    )
    return {**decision,"risk_metrics_available":True,"execution":"locked"}

@app.get("/v1/signals")
async def get_signals(user=Depends(current_user)):
    markets=await get_markets(user)
    return {"signals":[m for m in markets if m["signal"] in ("BUY","SELL")]}

@app.get("/v1/bot")
def get_bot(user=Depends(current_user)):
    import time
    cache_key=str(user["id"])
    now=time.monotonic()
    cached=_bot_state_cache.get(cache_key)
    if cached and now-cached[0] < _BOT_STATE_CACHE_TTL:
        return cached[1]
    with connection() as conn:
        row=conn.execute("SELECT running,emergency_stopped,mode,risk_per_trade,daily_loss_limit,max_open_trades,max_drawdown,updated_at FROM bot_state WHERE user_id=%s",(user["id"],)).fetchone()
    if not row: raise HTTPException(500,"Bot state is not initialized")
    result={"running":row[0],"emergency_stopped":row[1],"mode":row[2],"risk_per_trade":float(row[3]),"daily_loss_limit":float(row[4]),"max_open_trades":int(row[5]),"max_drawdown":float(row[6]),"updated_at":row[7]}
    _bot_state_cache[cache_key]=(now,result)
    return result

class ModeSettings(BaseModel):
    mode: str

@app.put("/v1/bot/mode")
def update_mode(settings: ModeSettings,user=Depends(current_user)):
    allowed={"signals_only","semi_auto","full_auto"}
    if settings.mode not in allowed:
        raise HTTPException(400,"Mode must be signals_only, semi_auto, or full_auto")
    with connection() as conn:
        conn.execute("UPDATE bot_state SET mode=%s,updated_at=now() WHERE user_id=%s",(settings.mode,user["id"]))
    _bot_state_cache.pop(str(user["id"]),None)
    return get_bot(user)

@app.post("/v1/bot/start")
def start_bot(user=Depends(current_user)):
    with connection() as conn:
        row=conn.execute("SELECT emergency_stopped FROM bot_state WHERE user_id=%s",(user["id"],)).fetchone()
        if not row: raise HTTPException(500,"Bot state is not initialized")
        if row[0]: raise HTTPException(409,"Emergency stop is active. Reset it before starting the bot.")
        conn.execute("UPDATE bot_state SET running=true,updated_at=now() WHERE user_id=%s",(user["id"],))
    _bot_state_cache.pop(str(user["id"]),None)
    return get_bot(user)

@app.post("/v1/bot/stop")
def stop_bot(user=Depends(current_user)):
    with connection() as conn: conn.execute("UPDATE bot_state SET running=false,updated_at=now() WHERE user_id=%s",(user["id"],))
    _bot_state_cache.pop(str(user["id"]),None)
    return get_bot(user)

@app.post("/v1/bot/emergency-stop")
def emergency_stop(user=Depends(current_user)):
    with connection() as conn: conn.execute("UPDATE bot_state SET running=false,emergency_stopped=true,updated_at=now() WHERE user_id=%s",(user["id"],))
    _bot_state_cache.pop(str(user["id"]),None)
    notification_event(user["id"],"notification_emergency_stop",{"message":"Emergency stop activated"})
    send_push(user["id"],"Emergency stop activated","New trading has been disabled.",{"type":"emergency_stop"})
    return {"ok":True,"message":"New trading disabled and bot stopped","state":get_bot(user)}

@app.post("/v1/bot/reset-emergency")
def reset_emergency(user=Depends(current_user)):
    with connection() as conn: conn.execute("UPDATE bot_state SET emergency_stopped=false,updated_at=now() WHERE user_id=%s",(user["id"],))
    _bot_state_cache.pop(str(user["id"]),None)
    return get_bot(user)

@app.put("/v1/bot/risk")
def update_risk(settings:RiskSettings,user=Depends(current_user)):
    with connection() as conn:
        conn.execute("UPDATE bot_state SET risk_per_trade=%s,daily_loss_limit=%s,max_open_trades=%s,max_drawdown=%s,updated_at=now() WHERE user_id=%s",(settings.risk_per_trade,settings.daily_loss_limit,settings.max_open_trades,settings.max_drawdown,user["id"]))
    _risk_cache.pop(str(user["id"]),None)
    _account_route_cache.pop(str(user["id"]),None)
    _bot_state_cache.pop(str(user["id"]),None)
    return get_bot(user)


