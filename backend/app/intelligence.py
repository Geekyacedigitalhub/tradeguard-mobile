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

def market_intelligence(signal:dict, candles_5m:list):
    """Build an explainable snapshot from the current validated MTF signal."""
    if not candles_5m:
        return {"regime":"UNKNOWN","session":"UNKNOWN","levels":{},"why_not_trade":["No 5M candles available"]}

    closes=[float(c.close) for c in candles_5m[-60:]]
    highs=[float(c.high) for c in candles_5m[-60:]]
    lows=[float(c.low) for c in candles_5m[-60:]]
    current=closes[-1]
    recent_high=max(highs[:-1]) if len(highs)>1 else highs[-1]
    recent_low=min(lows[:-1]) if len(lows)>1 else lows[-1]
    rng=max(recent_high-recent_low,1e-12)
    position=(current-recent_low)/rng

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

    reasons=[]
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
    if not reasons and signal.get("signal") in ("BUY","SELL"):
        reasons.append("Executable conditions are currently aligned")

    timestamp=candles_5m[-1].time
    if timestamp:
        session=_session(datetime.fromtimestamp(int(timestamp),tz=timezone.utc).hour)
    else:
        session="UNKNOWN"

    return {
        "regime":regime,
        "session":session,
        "price_position_pct":round(position*100,1),
        "levels":{
            "recent_high":round(recent_high,8),
            "recent_low":round(recent_low,8),
            "range":round(rng,8),
        },
        "why_not_trade":reasons[:6],
        "market_structure":{
            "higher_high_context":current>recent_high,
            "lower_low_context":current<recent_low,
            "range_position":"UPPER" if position>=0.66 else "LOWER" if position<=0.34 else "MID",
        },
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
