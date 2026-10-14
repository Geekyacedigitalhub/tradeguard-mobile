import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from .auth import _decode_token, current_user
from .auth_api import router as auth_router
from .notifications_api import router as notifications_router, send_push, notification_event
from .bridge_api import router as bridge_router
from .ctrader_oauth_api import router as ctrader_oauth_router
from .bridge_sync_api import router as bridge_sync_router
from .db import connection, ensure_schema
from .market_data import candles_for, latest_price, sync_cloud_market_data
from .strategy import analyze_multi_timeframe, analyze_selected_strategy, backtest_strategy
from .risk_api import approve_trade
from .risk_metrics import consecutive_losses
from .intelligence import market_intelligence
from .technical_engine import deep_market_analysis
from .knowledge_api import router as knowledge_router
from .validation_gate import latest_validation_gate
from .profit_engine import evaluate_opportunity, rank_opportunities
from .learning import learning_gate
from .optimizer import optimizer_gate
from .trade_api import router as trade_router, queue_bridge_command, mt5_connected
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

# Short-lived process-local cache keeps the mobile scanner responsive while
# the MT5 bridge continues refreshing the underlying candles.
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

# Process-local live market stream. Ticks are never written to Neon; the MT5 bridge publishes them here and connected mobile charts receive them over WebSocket.
_LIVE_TICK_CONNECTIONS:dict[str,set[WebSocket]]={}


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
                    config = _read_bot_configuration(str(user_id))
                    risk_multiplier = {"conservative": 0.5, "moderate": 1.0, "aggressive": 1.25}.get(config.get("risk_tolerance"), 0.5)
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
                        risk_per_trade=min(float(risk[0]) * risk_multiplier * float(signal.get("profit_engine",{}).get("risk_multiplier",1.0)), 1.0),
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
                        # Auto mode must use the real cloud MT5 execution path.
                        # Never silently fall back to a paper/local position: if the
                        # cloud EA heartbeat is stale, fail closed and wait.
                        provider=execution_provider(str(user_id))
                        # TradeGuard is cTrader-cloud-only. Never route a live order
                        # through a legacy MT5 bridge or silently fall back to another
                        # execution provider.
                        if provider != "ctrader" or not decision.get("broker_volume_verified") or not decision.get("broker_volume"):
                            notification_event(user_id,"notification_trade_execution_blocked",{
                                "symbol":signal_symbol,
                                "action":signal.get("signal"),
                                "reason":(
                                    "cTrader cloud execution is unavailable; trade was blocked."
                                    if provider != "ctrader"
                                    else "Automated entry blocked: broker-validated cTrader volume and account-currency conversion are not available."
                                ),
                            })
                            continue
                        command_id=queue_bridge_command(
                            str(user_id),
                            "open_market",
                            {
                                "execution_provider":"ctrader",
                                "broker_volume":int(decision["broker_volume"]),
                                "symbol":signal.get("ctrader_symbol") or str(signal_symbol).replace("/",""),
                                "side":signal.get("signal"),
                                "risk_amount":float(decision["risk_amount"]),
                                "stop_loss":signal.get("stop_loss"),
                                "take_profit":signal.get("take_profit"),
                                "reason":"TradeGuard Auto Execution",
                                "entry":signal.get("entry"),
                                "learning_context":{
                                    "setup":"TradeGuard MTF Price Action v2",
                                    "timeframe":"MTF",
                                    "session":(signal.get("intelligence") or {}).get("session"),
                                    "regime":(signal.get("intelligence") or {}).get("regime"),
                                    "volatility":(signal.get("intelligence") or {}).get("volatility"),
                                    "edge_score":(signal.get("profit_engine") or {}).get("edge_score"),
                                    "expectancy_r":(signal.get("profit_engine") or {}).get("expectancy_r"),
                                    "risk_multiplier":(signal.get("profit_engine") or {}).get("risk_multiplier"),
                                },
                            },
                        )
                        execution_label="CTRADER_CLOUD"
                        notification_event(user_id,"notification_trade_approval_needed",{
                            "symbol":signal_symbol,
                            "action":signal.get("signal"),
                            "quantity":decision.get("quantity"),
                            "reason":f"Risk checks passed; {execution_label} execution queued.",
                            "command_id":command_id,
                            "execution":execution_label,
                        })
                        send_push(
                            user_id,
                            f"Trade queued · {signal_symbol}",
                            f"{signal.get('signal')} approved · {execution_label} execution queued.",
                            {"type":"trade_execution_queued","command_id":command_id,"symbol":signal_symbol},
                        )
                    elif mode=="semi_auto":
                        notification_event(user_id,"notification_trade_approval_needed",{"symbol":signal.get("symbol",symbol),"action":signal.get("signal"),"quantity":decision.get("quantity"),"reason":"Risk checks passed; manual approval required"})
                except Exception:
                    continue
    except Exception:
        pass

async def multi_timeframe_analysis(symbol,user_id,config=None):
    """Build one setup from 1H regime, 15M structure, and 5M entry trigger."""
    symbol=symbol.upper()
    user_id=str(user_id)
    config = config or _read_bot_configuration(user_id)
    strategy_name = config.get("strategy", "institutional")
    frequency = config.get("frequency", "scalping")
    cache_key=(user_id,symbol,strategy_name,frequency)
    now=__import__("time").monotonic()
    cached=_ANALYSIS_CACHE.get(cache_key)
    if cached and now-cached["time"] < _ANALYSIS_CACHE_TTL:
        return cached["result"]

    task=_ANALYSIS_TASKS.get(cache_key)
    if task is None:
        async def run_analysis():
            interval_sets = {
                "scalping": ("1h", "15m", "5m"),
                "intraday": ("1h", "15m", "15m"),
                "swing": ("1h", "1h", "15m"),
            }
            interval_h1, interval_m15, interval_m5 = interval_sets.get(frequency, interval_sets["scalping"])
            candles_1h,candles_15m,candles_5m=await asyncio.gather(
                candles_for(symbol,interval=interval_h1,limit=220,user_id=user_id),
                candles_for(symbol,interval=interval_m15,limit=220,user_id=user_id),
                candles_for(symbol,interval=interval_m5,limit=220,user_id=user_id),
            )
            # Use the same completed-bar snapshot for the strategy and every
            # market-analysis gate. Provider feeds commonly include a forming bar.
            candles_1h = candles_1h[:-1]
            candles_15m = candles_15m[:-1]
            candles_5m = candles_5m[:-1]
            signal=analyze_selected_strategy(candles_1h,candles_15m,candles_5m,strategy_name)
            signal["strategy"] = strategy_name
            signal["frequency"] = frequency
            raw_signal=signal.get("signal")
            signal["deep_analysis"]=deep_market_analysis(
                candles_1h, candles_15m, candles_5m, candles_are_closed=True
            )
            # Respect the indicator selection stored for this user. Disabled
            # indicators are omitted from the active filter set but remain
            # calculated in diagnostic output for comparative research.
            indicator_selection = config.get("indicators", {})
            required_indicator_map = {
                "supertrend": "supertrend",
                "macd": "macd",
                "adx_di": "adx_di",
                "chandelier_exit": "chandelier_exit",
                "wavetrend": "wavetrend",
            }
            active_indicators = [
                key for key, enabled in indicator_selection.items()
                if enabled and key in required_indicator_map
            ]
            selected_frames = signal["deep_analysis"].get("timeframes", {})
            for frame in selected_frames.values():
                readings = frame.get("selected_indicators", {})
                frame["active_indicators"] = {
                    key: readings[key] for key in active_indicators if key in readings
                }
            signal["deep_analysis"]["indicator_selection"] = {
                key: bool(indicator_selection.get(key, False))
                for key in required_indicator_map
            }
            signal["deep_analysis"]["active_indicator_names"] = active_indicators
            # Explicit confirmation filter: selected trend/momentum indicators can
            # veto an otherwise directional entry, but can never create a BUY/SELL.
            # Chandelier Exit remains an exit-level reference, not an entry trigger.
            indicator_checks = []
            if raw_signal in ("BUY", "SELL"):
                expected = "BULLISH" if raw_signal == "BUY" else "BEARISH"
                check_frames = (("1h", selected_frames.get("1h", {})), ("15m", selected_frames.get("15m", {})))

                # Every enabled confirmation indicator must produce usable evidence
                # on its required timeframe. Missing/short candle history is a veto,
                # never an implicit pass. Chandelier Exit remains informational only.
                for frame_name, frame in check_frames:
                    active = frame.get("active_indicators", {})
                    for indicator_name in ("supertrend", "macd"):
                        if not indicator_selection.get(indicator_name, False):
                            continue
                        reading = active.get(indicator_name)
                        actual = reading.get("direction") if isinstance(reading, dict) else None
                        passed = actual == expected
                        indicator_checks.append({
                            "indicator": indicator_name,
                            "timeframe": frame_name,
                            "expected": expected,
                            "actual": actual or "INSUFFICIENT_OR_MISSING",
                            "passed": passed,
                        })

                for frame_name, frame in check_frames:
                    if not indicator_selection.get("adx_di", False):
                        continue
                    reading = frame.get("active_indicators", {}).get("adx_di")
                    directional_key = "plus_di" if raw_signal == "BUY" else "minus_di"
                    opposing_key = "minus_di" if raw_signal == "BUY" else "plus_di"
                    adx_value = reading.get("adx") if isinstance(reading, dict) else None
                    directional_value = reading.get(directional_key) if isinstance(reading, dict) else None
                    opposing_value = reading.get(opposing_key) if isinstance(reading, dict) else None
                    passed = (
                        isinstance(adx_value, (int, float))
                        and isinstance(directional_value, (int, float))
                        and isinstance(opposing_value, (int, float))
                        and adx_value >= 18
                        and directional_value > opposing_value
                    )
                    indicator_checks.append({
                        "indicator": "adx_di",
                        "timeframe": frame_name,
                        "expected": expected,
                        "actual": reading.get("regime") if isinstance(reading, dict) else "INSUFFICIENT_OR_MISSING",
                        "passed": passed,
                    })

                if indicator_selection.get("wavetrend", False):
                    wave = selected_frames.get("5m", {}).get("active_indicators", {}).get("wavetrend")
                    # WaveTrend is selected as a crossover confirmation, not a
                    # persistent WT1-vs-WT2 state. Require a fresh, closed-candle
                    # cross in the signal direction; missing/neutral crosses veto.
                    actual = wave.get("cross") if isinstance(wave, dict) else None
                    indicator_checks.append({
                        "indicator": "wavetrend",
                        "timeframe": "5m",
                        "expected": expected,
                        "actual": actual or "INSUFFICIENT_OR_MISSING",
                        "passed": actual == expected,
                    })
            indicator_filter_passed = all(check["passed"] for check in indicator_checks)
            signal["deep_analysis"]["indicator_filter"] = {
                "enabled": bool(indicator_checks),
                "passed": indicator_filter_passed,
                "checks": indicator_checks,
                "vetoes": [
                    f"{check['indicator']} ({check['timeframe']}) conflicts with {raw_signal}"
                    for check in indicator_checks if not check["passed"]
                ],
                "note": "Selected confirmation indicators can veto entries; they never create signals. Chandelier Exit is informational only.",
            }
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
            indicator_filter = signal["deep_analysis"].get("indicator_filter", {})
            indicator_vetoes = indicator_filter.get("vetoes", [])
            indicator_gate_ok = not indicator_filter.get("enabled") or indicator_filter.get("passed", False)
            strategy_gate_ok = (
                deep_decision == "TRADE CANDIDATE"
                if strategy_name == "institutional"
                else raw_signal in ("BUY", "SELL")
            )
            signal["trade_candidate"] = (
                strategy_gate_ok
                and profit_decision == "EXECUTE"
                and indicator_gate_ok
            )
            if raw_signal in ("BUY","SELL") and not signal["trade_candidate"]:
                signal["signal"]="WATCH"
                if not indicator_gate_ok:
                    signal["reason"]="Selected indicator filter rejected setup · " + " · ".join(indicator_vetoes)
                else:
                    signal["reason"]=(
                        f"Research/profit gate rejected execution · {signal['deep_analysis'].get('summary') or deep_decision or 'NO TRADE'}"
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
            users=conn.execute("SELECT DISTINCT user_id FROM bridge_pairings").fetchall()
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

                    config = _read_bot_configuration(user_id)
                    risk_multiplier = {"conservative": 0.5, "moderate": 1.0, "aggressive": 1.25}.get(config.get("risk_tolerance"), 0.5)
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
                    if not account or not risk:
                        continue

                    if any(p.symbol == signal_symbol.replace("USDT","/USD") for p in open_now):
                        continue

                    decision=approve_trade(
                        signal,
                        balance=float(account["balance"]),
                        equity=float(account["equity"]),
                        today_pnl_percent=(float(account["today_pl"])/max(float(account["balance"]),1))*100,
                        drawdown_percent=float(account["drawdown"]),
                        open_trades=len(open_now),
                        consecutive_losses=loss_streak,
                        risk_per_trade=min(float(risk[0]) * risk_multiplier, 1.0),
                        daily_loss_limit=float(risk[1]),
                        max_open_trades=int(risk[2]),
                        max_drawdown=float(risk[3]),
                    )

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
                        "historical_gate":historical_gate,
                        "deep_research_gate":deep_gate,
                    }

                    with connection() as conn:
                        conn.execute(
                            "INSERT INTO signals (user_id,symbol,action,score,reason,entry,stop_loss,take_profit) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                            (user_id,signal_symbol,action,score,signal.get("reason"),signal.get("entry"),signal.get("stop_loss"),signal.get("take_profit"))
                        )
                    notification_event(user_id,"notification_signal",payload)

                    auto_approved=False
                    command_id=None
                    if settings["enabled"] and score >= settings["min_score"] and decision.get("approved") and historical_gate.get("approved") and deep_gate and profit_gate and execution_provider(user_id)=="ctrader" and decision.get("broker_volume_verified") and decision.get("broker_volume"):
                        command_id=queue_bridge_command(
                            user_id,
                            "open_market",
                            {
                                "execution_provider":"ctrader",
                                "broker_volume":int(decision["broker_volume"]),
                                "symbol":signal.get("ctrader_symbol") or str(signal_symbol).replace("/",""),
                                "side":action,
                                "risk_amount":float(decision["risk_amount"]),
                                "quantity":float(decision["quantity"]),
                                "stop_loss":signal.get("stop_loss"),
                                "take_profit":signal.get("take_profit"),
                                "reason":"TradeGuard AI Auto-Approval",
                                "entry":signal.get("entry"),
                                "learning_context":{
                                    "setup":"TradeGuard MTF Price Action v2","timeframe":"MTF",
                                    "session":(signal.get("intelligence") or {}).get("session"),
                                    "regime":(signal.get("intelligence") or {}).get("regime"),
                                    "volatility":(signal.get("intelligence") or {}).get("volatility"),
                                    "edge_score":(signal.get("profit_engine") or {}).get("edge_score"),
                                    "expectancy_r":(signal.get("profit_engine") or {}).get("expectancy_r"),
                                    "risk_multiplier":(signal.get("profit_engine") or {}).get("risk_multiplier"),
                                },
                            }
                        )
                        auto_approved=True

                    if auto_approved:
                        notification_event(user_id,"notification_trade_approval_needed",
                            {**payload,"ai_approved":True,"command_id":command_id,"execution":"CTRADER_DEMO"})
                        send_push(
                            user_id,
                            f"AI APPROVED · {action} {signal_symbol}",
                            f"AI approved {action} · score {int(score)} · entry {signal.get('entry')} · cTrader demo execution queued.",
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
app.include_router(bridge_router)
app.include_router(ctrader_oauth_router)
app.include_router(bridge_sync_router)
app.include_router(trade_router)
app.include_router(validation_router)
app.include_router(journal_router)
app.include_router(knowledge_router)

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
        result={"connected":False,"stale":True,"provider":"mt5_cloud_ea","terminal":"MT5 Cloud EA","environment":"demo","message":"Cloud MT5 terminal is not connected. Trading is unavailable until the cloud EA heartbeat is active."}
        _broker_status_cache[cache_key]=(now,result)
        return result
    payload=row[0] or {}
    # account_state.updated_at is refreshed by the EA heartbeat.
    # broker_connection.created_at is only a snapshot-change timestamp.
    last_seen=row[2] or row[1]
    stale=not last_seen or (datetime.now(timezone.utc)-last_seen).total_seconds()>45
    is_cloud_ea=payload.get("terminal")=="MT5 Cloud EA"
    connected=bool(payload.get("connected",False)) and not stale and is_cloud_ea
    result={
        "connected":connected,
        "stale":stale,
        "last_seen":last_seen,
        "provider":"mt5_cloud_ea" if is_cloud_ea else payload.get("provider","none"),
        "terminal":payload.get("terminal"),
        "environment":payload.get("environment","demo"),
        "account":payload.get("account"),
        "message":(
            "Cloud MT5 terminal heartbeat is stale. The cloud EA must be running."
            if stale or not is_cloud_ea
            else "Cloud MT5 terminal is active."
        ),
    }
    _broker_status_cache[cache_key]=(now,result)
    return result

class RiskSettings(BaseModel):
    risk_per_trade:float=Field(0.5,ge=0.1,le=5)
    daily_loss_limit:float=Field(2.0,ge=0.5,le=20)
    max_open_trades:int=Field(3,ge=1,le=20)
    max_drawdown:float=Field(5.0,ge=1,le=50)

class BotConfiguration(BaseModel):
    strategy: str = "institutional"
    risk_tolerance: str = "conservative"
    frequency: str = "scalping"
    indicators: dict[str, bool] = Field(default_factory=lambda: {
        "supertrend": True,
        "macd": True,
        "adx_di": True,
        "chandelier_exit": True,
        "wavetrend": False,
    })

    @classmethod
    def validate_values(cls, values):
        if values.strategy not in {"institutional", "reversal", "breakout"}:
            raise ValueError("Unsupported strategy")
        if values.risk_tolerance not in {"conservative", "moderate", "aggressive"}:
            raise ValueError("Unsupported risk tolerance")
        if values.frequency not in {"scalping", "intraday", "swing"}:
            raise ValueError("Unsupported trading frequency")
        allowed_indicators = {"supertrend", "macd", "adx_di", "chandelier_exit", "wavetrend"}
        if not isinstance(values.indicators, dict) or set(values.indicators) - allowed_indicators:
            raise ValueError("Unsupported indicator selection")
        if any(not isinstance(enabled, bool) for enabled in values.indicators.values()):
            raise ValueError("Indicator selections must be boolean")
        return values


def _read_bot_configuration(user_id: str):
    with connection() as conn:
        row = conn.execute(
            "SELECT payload FROM audit_events WHERE user_id=%s AND event_type='bot_configuration' ORDER BY created_at DESC LIMIT 1",
            (user_id,),
        ).fetchone()
    payload = row[0] if row and isinstance(row[0], dict) else {}
    default_indicators = {
        "supertrend": True, "macd": True, "adx_di": True,
        "chandelier_exit": True, "wavetrend": False,
    }
    saved_indicators = payload.get("indicators", {})
    if not isinstance(saved_indicators, dict):
        saved_indicators = {}
    indicators = {
        name: saved_indicators.get(name, default)
        for name, default in default_indicators.items()
    }
    return {
        "strategy": payload.get("strategy", "institutional"),
        "risk_tolerance": payload.get("risk_tolerance", "conservative"),
        "frequency": payload.get("frequency", "scalping"),
        "indicators": indicators,
    }


@app.get("/v1/bot/configuration")
def get_bot_configuration(user=Depends(current_user)):
    return _read_bot_configuration(str(user["id"]))


@app.put("/v1/bot/configuration")
def update_bot_configuration(settings: BotConfiguration, user=Depends(current_user)):
    values = settings.model_dump()
    try:
        BotConfiguration.validate_values(settings)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    with connection() as conn:
        conn.execute(
            "INSERT INTO audit_events (user_id,event_type,payload) VALUES (%s,'bot_configuration',%s::jsonb)",
            (user["id"], __import__("json").dumps(values)),
        )
        # A configuration change must not silently restart a stopped bot.
        conn.execute(
            "UPDATE bot_state SET updated_at=now() WHERE user_id=%s",
            (user["id"],),
        )
    _bot_state_cache.pop(str(user["id"]), None)
    _ANALYSIS_CACHE.clear()
    return values


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
    print(
        "CLOUD_SYNC "
        f"updated={report.get('updated', 0)} "
        f"failed={report.get('failed', 0)} "
        f"time={report.get('time', '')}",
        flush=True,
    )
    return {"ok": report.get("failed", 0) == 0, "updated": report.get("updated", 0), "failed": report.get("failed", 0), "time": report.get("time")}


class LiveTicks(BaseModel):
    user_id:str
    ticks:list[dict]=[]

@app.post("/v1/internal/live-ticks")
async def live_ticks(
    body:LiveTicks,
    x_bridge_secret:str|None=Header(default=None),
    x_bridge_user:str|None=Header(default=None),
    x_bridge_id:str|None=Header(default=None),
    x_bridge_token:str|None=Header(default=None),
):
    expected=os.getenv("MT5_BRIDGE_SECRET","").strip()
    bridge_id=x_bridge_id or "cloud-mt5-ea"
    if x_bridge_token:
        from .bridge_api import require_bridge
        require_bridge(None,x_bridge_user,bridge_id,token=x_bridge_token)
    elif not expected or not x_bridge_secret or x_bridge_secret != expected:
        raise HTTPException(401,"Invalid bridge credentials")
    if bridge_id!="cloud-mt5-ea" or not x_bridge_user or str(x_bridge_user)!=str(body.user_id):
        raise HTTPException(403,"Invalid cloud MT5 EA identity")
    connections=list(_LIVE_TICK_CONNECTIONS.get(str(body.user_id),set()))
    delivered=0
    for tick in body.ticks:
        symbol=str(tick.get("symbol","")).upper()
        if not symbol:
            continue
        payload={
            "type":"tick",
            "tick":{
                "symbol":symbol,
                "bid":float(tick.get("bid") or 0),
                "ask":float(tick.get("ask") or 0),
                "price":float(tick.get("price") or 0),
                "time":int(tick.get("time") or 0),
                "time_msc":int(tick.get("time_msc") or 0),
            },
        }
        for websocket in connections:
            try:
                await websocket.send_json(payload)
                delivered+=1
            except Exception:
                _LIVE_TICK_CONNECTIONS.get(str(body.user_id),set()).discard(websocket)
    return {"ok":True,"ticks":len(body.ticks),"delivered":delivered}

@app.websocket("/v1/market-stream")
async def market_stream(websocket:WebSocket):
    token=websocket.query_params.get("token")
    try:
        if not token:
            raise ValueError("missing token")
        user_id=_decode_token(token)
    except Exception:
        await websocket.close(code=1008,reason="Invalid authentication token")
        return

    await websocket.accept()
    connections=_LIVE_TICK_CONNECTIONS.setdefault(user_id,set())
    connections.add(websocket)
    await websocket.send_json({"type":"connected","stream":"mt5-ticks"})
    try:
        while True:
            # The mobile client does not need to send data. Waiting for a
            # client frame keeps the socket alive and lets disconnects be
            # detected without polling Neon.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        connections.discard(websocket)
        if not connections:
            _LIVE_TICK_CONNECTIONS.pop(user_id,None)

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
    if mt5_connected(user["id"]):
        with connection() as conn:
            row=conn.execute(
                "SELECT payload FROM audit_events WHERE user_id=%s AND event_type='broker_connection' ORDER BY created_at DESC LIMIT 1",
                (user["id"],)
            ).fetchone()
        payload=row[0] if row else {}
        broker_positions=payload.get("positions") if isinstance(payload.get("positions"),list) else None
    open_count=len(broker_positions) if broker_positions is not None else len(list_positions("open",user["id"]))
    if not account or not bot: raise HTTPException(500,"Account state is not initialized")

    result={
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
    with connection() as conn:
        row=conn.execute("""
            SELECT a.balance,a.equity,a.today_pl,a.drawdown,
                   b.risk_per_trade,b.daily_loss_limit,b.max_open_trades,b.max_drawdown
            FROM account_state a
            JOIN bot_state b ON b.user_id=a.user_id
            WHERE a.user_id=%s
        """,(user["id"],)).fetchone()
    if not row: raise HTTPException(500,"Risk state is not initialized")
    return approve_trade(signal,balance=float(row[0]),equity=float(row[1]),consecutive_losses=consecutive_losses(user["id"]),risk_per_trade=float(row[4]),daily_loss_limit=float(row[5]),max_open_trades=int(row[6]),max_drawdown=float(row[7]))

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


