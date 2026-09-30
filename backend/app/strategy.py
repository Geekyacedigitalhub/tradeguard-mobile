from dataclasses import dataclass
from typing import Literal

Signal = Literal["BUY", "SELL", "WATCH", "NO TRADE"]

@dataclass
class Candle:
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

def ema(values, period):
    if len(values) < period:
        return sum(values) / len(values)
    k = 2 / (period + 1)
    value = sum(values[:period]) / period
    for price in values[period:]:
        value = price * k + value * (1 - k)
    return value

def rsi(values, period=14):
    if len(values) <= period:
        return 50.0
    gains=[]; losses=[]
    for i in range(1,len(values)):
        d=values[i]-values[i-1]
        gains.append(max(d,0))
        losses.append(max(-d,0))
    ag=sum(gains[:period])/period
    al=sum(losses[:period])/period
    for i in range(period,len(gains)):
        ag=(ag*(period-1)+gains[i])/period
        al=(al*(period-1)+losses[i])/period
    return 100.0 if al==0 else 100-(100/(1+ag/al))

def atr(candles, period=14):
    trs=[]
    for i,c in enumerate(candles):
        pc=candles[i-1].close if i else c.close
        trs.append(max(c.high-c.low,abs(c.low-pc),abs(c.high-pc)))
    return sum(trs[-period:])/min(period,len(trs))

def analyze(candles):
    if len(candles) < 200:
        return {"signal":"NO TRADE","score":0,"reason":"Insufficient market history for EMA200 confirmation"}

    closes=[c.close for c in candles]
    current=closes[-1]
    e20=ema(closes,20)
    e50=ema(closes,50)
    e200=ema(closes,200)
    rv=rsi(closes)
    av=atr(candles)

    buy=current > e20 > e50 > e200
    sell=current < e20 < e50 < e200

    score=25 if buy or sell else 0
    reasons=[
        "EMA trend bullish" if buy else
        "EMA trend bearish" if sell else
        "Trend conflict"
    ]

    momentum=(buy and 52 <= rv <= 72) or (sell and 28 <= rv <= 48)
    score += 20 if momentum else 0
    reasons.append("RSI momentum aligned" if momentum else "Momentum not aligned")

    recent=candles[-11:]
    resistance=max(c.high for c in recent[:-1])
    support=min(c.low for c in recent[:-1])
    broken=(buy and current > resistance) or (sell and current < support)
    score += 20 if broken else 0
    reasons.append("Recent structure break" if broken else "No structure break")

    vol_ok=av > 0 and av/current < 0.02
    score += 15 if vol_ok else 0
    reasons.append("Volatility acceptable" if vol_ok else "Volatility outside configured range")

    entry_ok=abs(current-e20) <= max(av*1.5,current*0.003)
    score += 10 if entry_ok else 0
    reasons.append("Entry near dynamic value" if entry_ok else "Entry stretched")

    last=candles[-1]
    body=abs(last.close-last.open)
    candle_ok=body >= av*0.15 and ((buy and last.close>last.open) or (sell and last.close<last.open))
    score += 10 if candle_ok else 0
    reasons.append("Price action confirms direction" if candle_ok else "Price action not confirmed")

    # A high score alone is not enough. An executable signal requires a
    # confirmed structure break in the direction of the EMA trend.
    executable = broken and score >= 70
    if buy and executable:
        signal="BUY"
    elif sell and executable:
        signal="SELL"
    elif score >= 55:
        signal="WATCH"
    else:
        signal="NO TRADE"

    side=1 if signal=="BUY" else -1 if signal=="SELL" else 0
    sl=current-av*1.5 if side==1 else current+av*1.5 if side==-1 else None
    tp=current+av*3 if side==1 else current-av*3 if side==-1 else None

    return {
        "signal":signal,
        "score":score,
        "reason":" · ".join(reasons),
        "entry":round(current,8),
        "stop_loss":round(sl,8) if sl else None,
        "take_profit":round(tp,8) if tp else None,
        "indicators":{
            "ema20":e20,
            "ema50":e50,
            "ema200":e200,
            "rsi":rv,
            "atr":av,
        }
    }
