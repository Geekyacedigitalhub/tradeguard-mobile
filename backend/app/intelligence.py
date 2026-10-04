from collections import Counter
from datetime import datetime, timezone
from statistics import median

def _session(hour_utc:int)->str:
    if 0 <= hour_utc < 8:
        return "ASIA"
    if 8 <= hour_utc < 13:
        return "LONDON"
    if 13 <= hour_utc < 17:
        return "NEW YORK"
    return "ASIA/NY OVERLAP"

STRATEGY_RULES={
    "name":"TradeGuard MTF Price Action v2",
    "regime":"1H EMA20/50/200 trend structure with RSI context",
    "setup":"15M trend, momentum, recent structure break and candle confirmation",
    "trigger":"5M directional breakout with candle confirmation",
    "protection":"ATR-based stop with fixed 1:2 target",
    "filters":["minimum historical context","timeframe alignment","structure confirmation","risk limits","consecutive-loss lockout"],
}

def _atr(candles, period=14):
    if not candles:
        return 0.0
    trs=[]
    for i,c in enumerate(candles):
        previous=candles[i-1].close if i else c.close
        trs.append(max(c.high-c.low,abs(c.low-previous),abs(c.high-previous)))
    return sum(trs[-period:])/min(period,len(trs))

def _trend_strength(closes):
    if len(closes)<20:
        return 0.0
    short=median(closes[-5:])
    long=median(closes[-20:])
    return abs(short-long)/max(abs(long),1e-12)*100

def _volatility_state(candles):
    if len(candles)<30:
        return "UNKNOWN"
    current_atr=_atr(candles[-30:],14)
    historical=[_atr(candles[max(0,i-14):i+1],14) for i in range(14,len(candles))]
    if not historical or current_atr<=0:
        return "UNKNOWN"
    baseline=median(historical)
    ratio=current_atr/max(baseline,1e-12)
    if ratio>=1.8:
        return "EXTREME"
    if ratio>=1.25:
        return "HIGH"
    if ratio<=0.65:
        return "LOW"
    return "NORMAL"

def _market_structure(candles):
    if len(candles)<12:
        return {"state":"UNKNOWN","range_position":"UNKNOWN","swing_high":None,"swing_low":None}
    highs=[float(c.high) for c in candles[-30:]]
    lows=[float(c.low) for c in candles[-30:]]
    current=float(candles[-1].close)
    swing_high=max(highs[:-1])
    swing_low=min(lows[:-1])
    span=max(swing_high-swing_low,1e-12)
    position=(current-swing_low)/span
    recent_high=max(highs[-6:-1])
    recent_low=min(lows[-6:-1])
    if current>recent_high:
        state="BREAKOUT_UP"
    elif current<recent_low:
        state="BREAKOUT_DOWN"
    elif position>=0.8:
        state="UPPER_RANGE"
    elif position<=0.2:
        state="LOWER_RANGE"
    else:
        state="RANGE"
    return {
        "state":state,
        "range_position":"UPPER" if position>=0.66 else "LOWER" if position<=0.34 else "MID",
        "swing_high":round(swing_high,8),
        "swing_low":round(swing_low,8),
    }

def _momentum_state(candles):
    if len(candles)<15:
        return "UNKNOWN"
    closes=[float(c.close) for c in candles[-15:]]
    change=(closes[-1]-closes[0])/max(abs(closes[0]),1e-12)*100
    if change>=0.25:
        return "BULLISH"
    if change<=-0.25:
        return "BEARISH"
    return "NEUTRAL"

def market_intelligence(signal:dict, candles_5m:list, deep_analysis:dict|None=None):
    """Build an explainable market-state snapshot; this is context, not a trade guarantee."""
    if not candles_5m:
        return {"regime":"UNKNOWN","session":"UNKNOWN","levels":{},"why_not_trade":["No 5M candles available"]}

    closes=[float(c.close) for c in candles_5m[-60:]]
    current=closes[-1]
    structure=_market_structure(candles_5m)
    volatility=_volatility_state(candles_5m)
    momentum=_momentum_state(candles_5m)
    strength=_trend_strength(closes)

    tf=signal.get("timeframes") or {}
    direction=tf.get("1h","NEUTRAL")
    setup=tf.get("15m","NO TRADE")
    trigger=signal.get("entry_trigger","waiting")
    score=float(signal.get("score") or 0)

    if direction=="BUY" and setup=="BUY":
        regime="BULLISH"
    elif direction=="SELL" and setup=="SELL":
        regime="BEARISH"
    else:
        regime="MIXED"

    warnings=[]
    if volatility=="EXTREME":
        warnings.append("Extreme volatility; normal stop/target assumptions may be unreliable")
    elif volatility=="HIGH":
        warnings.append("High volatility; execution risk is elevated")
    if regime=="BULLISH" and momentum=="BEARISH":
        warnings.append("Short-term momentum is opposing the higher-timeframe bias")
    if regime=="BEARISH" and momentum=="BULLISH":
        warnings.append("Short-term momentum is opposing the higher-timeframe bias")
    if structure["state"]=="UPPER_RANGE" and direction=="BUY":
        warnings.append("Price is near the upper part of the recent range; avoid chasing")
    if structure["state"]=="LOWER_RANGE" and direction=="SELL":
        warnings.append("Price is near the lower part of the recent range; avoid chasing")

    reasons=[]
    deep=deep_analysis or {}
    deep_decision=deep.get("decision")
    if deep_decision and deep_decision != "TRADE CANDIDATE":
        reasons.extend((deep.get("vetoes") or deep.get("reasons") or [])[:4])
    if signal.get("signal") not in ("BUY","SELL"):
        reasons.append(signal.get("reason") or "No executable setup")
    if direction not in ("BUY","SELL"):
        reasons.append("1H directional regime is not established")
    if setup not in ("BUY","SELL"):
        reasons.append("15M setup is not executable")
    if tf.get("5m") not in ("BUY","SELL"):
        reasons.append("5M direction is not aligned")
    if trigger!="5m_breakout":
        reasons.append("5M entry trigger is waiting")
    if score < 70:
        reasons.append(f"Validation score is below executable threshold ({score:.0f}/70)")
    reasons.extend(warnings)
    if not reasons and signal.get("signal") in ("BUY","SELL") and deep_decision in (None, "TRADE CANDIDATE"):
        reasons.append("Executable conditions are currently aligned")

    timestamp=candles_5m[-1].time
    session=_session(datetime.fromtimestamp(int(timestamp),tz=timezone.utc).hour) if timestamp else "UNKNOWN"

    return {
        "rules":STRATEGY_RULES,
        "regime":regime,
        "session":session,
        "momentum":momentum,
        "volatility":volatility,
        "trend_strength_pct":round(strength,4),
        "price_position_pct":round(((current-structure["swing_low"])/max(structure["swing_high"]-structure["swing_low"],1e-12))*100,1) if structure["swing_low"] is not None else None,
        "levels":{
            "recent_high":structure["swing_high"],
            "recent_low":structure["swing_low"],
            "range":round(structure["swing_high"]-structure["swing_low"],8) if structure["swing_high"] is not None else None,
        },
        "market_structure":structure,
        "warnings":warnings[:6],
        "why_not_trade":reasons[:8],
    }

def validation_summary(report:dict):
    trades=int(report.get("trades") or 0)
    if trades<=0:
        return {"quality":"NO_SAMPLE","sample_size":0,"notes":["No validated trades in the selected history."]}
    expectancy=float(report.get("expectancy_r") or 0)
    pf=report.get("profit_factor")
    dd=float(report.get("max_drawdown_r") or 0)
    notes=[]
    if trades<30: notes.append("Small historical sample; treat results as exploratory.")
    if expectancy<=0: notes.append("Historical expectancy is non-positive in this sample.")
    if pf is not None and float(pf)<1: notes.append("Gross losses exceed gross profits in this sample.")
    if dd>5: notes.append("Historical drawdown exceeded 5R.")
    if not notes: notes.append("Historical metrics are positive in this sample; continue testing across other periods and costs.")
    quality="POSITIVE_SAMPLE" if expectancy>0 and (pf is None or float(pf)>=1) else "MIXED_OR_NEGATIVE"
    return {"quality":quality,"sample_size":trades,"notes":notes}
