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
    time: int | None = None

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


def candle_structure(candles):
    """Describe the latest candle and common price-action patterns."""
    if len(candles) < 3:
        return {"pattern":"INSUFFICIENT","bullish":False,"bearish":False,"strength":0.0}

    a,b,last=candles[-3],candles[-2],candles[-1]
    rng=max(last.high-last.low,1e-12)
    body=abs(last.close-last.open)
    upper=last.high-max(last.open,last.close)
    lower=min(last.open,last.close)-last.low
    close_pos=(last.close-last.low)/rng

    bullish=last.close>last.open
    bearish=last.close<last.open
    prev_bullish=b.close>b.open
    prev_bearish=b.close<b.open

    bullish_engulf=(
        bullish and prev_bearish and
        last.open<=b.close and last.close>=b.open
    )
    bearish_engulf=(
        bearish and prev_bullish and
        last.open>=b.close and last.close<=b.open
    )

    bullish_pin=(
        lower>=body*2.0 and
        upper<=max(body,1e-12)*1.2 and
        close_pos>=0.65
    )
    bearish_pin=(
        upper>=body*2.0 and
        lower<=max(body,1e-12)*1.2 and
        close_pos<=0.35
    )

    inside_bar=last.high<=b.high and last.low>=b.low

    # A strong directional candle closes near its extreme and has a
    # meaningful body relative to its own range.
    strong_bull=bullish and body/rng>=0.60 and close_pos>=0.75
    strong_bear=bearish and body/rng>=0.60 and close_pos<=0.25

    if bullish_engulf:
        pattern="BULLISH ENGULFING"
        strength=1.0
    elif bearish_engulf:
        pattern="BEARISH ENGULFING"
        strength=1.0
    elif bullish_pin:
        pattern="BULLISH PIN BAR"
        strength=0.85
    elif bearish_pin:
        pattern="BEARISH PIN BAR"
        strength=0.85
    elif strong_bull:
        pattern="STRONG BULLISH CLOSE"
        strength=0.75
    elif strong_bear:
        pattern="STRONG BEARISH CLOSE"
        strength=0.75
    elif inside_bar:
        pattern="INSIDE BAR"
        strength=0.45
    else:
        pattern="NEUTRAL CANDLE"
        strength=0.0

    return {
        "pattern":pattern,
        "bullish":bullish or bullish_engulf or bullish_pin or strong_bull,
        "bearish":bearish or bearish_engulf or bearish_pin or strong_bear,
        "strength":strength,
        "body_ratio":body/rng,
        "close_position":close_pos,
    }


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

    candle=candle_structure(candles)
    candle_direction_ok=(buy and candle["bullish"]) or (sell and candle["bearish"])
    candle_ok=candle_direction_ok and candle["strength"]>=0.45 and candle["body_ratio"]>=0.25
    score += 10 if candle_ok else 0
    reasons.append(
        f"Candle confirms direction ({candle['pattern']})"
        if candle_ok else
        f"Candle not confirmed ({candle['pattern']})"
    )

    # A high score alone is not enough. An can_execute signal requires a
    # confirmed structure break in the direction of the EMA trend.
    # A trade must have trend, structure, and momentum confirmation.
    # This prevents an overextended RSI from producing an can_execute signal.
    can_execute = broken and momentum and score >= 70
    if buy and can_execute:
        signal="BUY"
    elif sell and can_execute:
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


def _trend_bias(candles):
    """Return the directional bias from EMA structure and RSI without requiring a trade trigger."""
    if len(candles) < 200:
        return {"bias":"NEUTRAL","score":0,"ema20":None,"ema50":None,"ema200":None,"rsi":50.0}
    closes=[c.close for c in candles]
    current=closes[-1]
    e20=ema(closes,20)
    e50=ema(closes,50)
    e200=ema(closes,200)
    rv=rsi(closes)
    if current > e20 > e50 > e200:
        bias="BUY"
    elif current < e20 < e50 < e200:
        bias="SELL"
    else:
        bias="NEUTRAL"
    return {
        "bias":bias,
        "score":25 if bias!="NEUTRAL" else 0,
        "ema20":e20,
        "ema50":e50,
        "ema200":e200,
        "rsi":rv,
    }


def _entry_trigger(candles, direction):
    """Detect a fresh lower-timeframe breakout/retest-style trigger."""
    if len(candles) < 30 or direction not in ("BUY","SELL"):
        return {"confirmed":False,"reason":"Insufficient lower-timeframe trigger history"}

    recent=candles[-11:]
    prior=recent[:-1]
    last=candles[-1]
    previous=candles[-2]
    resistance=max(c.high for c in prior)
    support=min(c.low for c in prior)
    av=atr(candles)
    candle=candle_structure(candles)
    bullish=last.close > last.open
    bearish=last.close < last.open

    if direction=="BUY":
        breakout=last.close > resistance
        retest=previous.high >= resistance and last.close > resistance
        candle_ok=(
            candle["bullish"] and
            candle["strength"]>=0.45 and
            candle["body_ratio"]>=0.25
        )
        confirmed=breakout and candle_ok
    else:
        breakout=last.close < support
        retest=previous.low <= support and last.close < support
        candle_ok=(
            candle["bearish"] and
            candle["strength"]>=0.45 and
            candle["body_ratio"]>=0.25
        )
        confirmed=breakout and candle_ok

    return {
        "confirmed":confirmed,
        "breakout":breakout,
        "retest":retest,
        "candle_confirmation":candle_ok,
        "pattern":candle["pattern"],
        "body_ratio":candle["body_ratio"],
        "reason":(
            f"Lower-timeframe breakout confirmed · {candle['pattern']}"
            if confirmed else
            f"Lower-timeframe trigger not confirmed · {candle['pattern']}"
        ),
    }


def analyze_multi_timeframe(candles_1h, candles_15m, candles_5m):
    """
    Multi-timeframe setup engine:
      1H = directional regime
      15M = structure/momentum setup
      5M = entry trigger
    A BUY/SELL is emitted only when all three agree and the 5M trigger fires.
    """
    if min(len(candles_1h),len(candles_15m),len(candles_5m)) < 200:
        return {
            "signal":"NO TRADE",
            "score":0,
            "reason":"Insufficient multi-timeframe history",
            "timeframes":{"1h":"INSUFFICIENT","15m":"INSUFFICIENT","5m":"INSUFFICIENT"},
        }

    h1=_trend_bias(candles_1h)
    m15=analyze(candles_15m)
    m5=_trend_bias(candles_5m)

    h1_bias=h1["bias"]
    m15_signal=m15.get("signal")
    m5_bias=m5["bias"]

    direction=None
    if h1_bias in ("BUY","SELL") and h1_bias==m5_bias and m15_signal==h1_bias:
        direction=h1_bias

    if direction is None:
        aligned=(h1_bias in ("BUY","SELL") and h1_bias==m5_bias and m15_signal in ("BUY","SELL"))
        score=45 if aligned else 25 if h1_bias in ("BUY","SELL") else 0
        return {
            "signal":"WATCH" if score>=45 else "NO TRADE",
            "score":score,
            "reason":f"Timeframe alignment incomplete · 1H {h1_bias} · 15M {m15_signal} · 5M {m5_bias}",
            "timeframes":{"1h":h1_bias,"15m":m15_signal,"5m":m5_bias},
            "indicators":{
                "h1_rsi":h1["rsi"],
                "m15_rsi":m15.get("indicators",{}).get("rsi"),
                "m5_rsi":m5["rsi"],
                "candle_pattern":candle_structure(candles_5m)["pattern"],
            },
        }

    trigger=_entry_trigger(candles_5m,direction)
    score=30  # aligned 1H + 15M + 5M regime
    score += 25 if m15.get("score",0)>=70 else 15
    score += 20 if trigger["confirmed"] else 0
    score += 10 if trigger["candle_confirmation"] else 0

    current=candles_5m[-1].close
    av=atr(candles_5m)
    entry=current
    sl=current-av*1.5 if direction=="BUY" else current+av*1.5
    tp=current+av*3 if direction=="BUY" else current-av*3

    can_execute=trigger["confirmed"] and score>=70
    signal=direction if can_execute else "WATCH"

    reasons=[
        f"1H bias {h1_bias}",
        f"15M setup {m15_signal}",
        f"5M bias {m5_bias}",
        trigger["reason"],
        "Risk/reward target 1:2",
    ]

    return {
        "signal":signal,
        "score":score,
        "reason":" · ".join(reasons),
        "entry":round(entry,8),
        "stop_loss":round(sl,8),
        "take_profit":round(tp,8),
        "timeframe":"MTF",
        "entry_trigger":"5m_breakout" if trigger["confirmed"] else "waiting",
        "timeframes":{
            "1h":h1_bias,
            "15m":m15_signal,
            "5m":m5_bias,
        },
        "trigger":trigger,
        "indicators":{
            "h1_rsi":h1["rsi"],
            "m15_rsi":m15.get("indicators",{}).get("rsi"),
            "m5_rsi":m5["rsi"],
            "m5_atr":av,
            "candle_pattern":trigger["pattern"],
        },
    }


def backtest_strategy(candles, warmup=200, horizon=24, cost_r=0.0):
    """Walk forward through candles without using future data for the signal.

    cost_r is a fixed round-trip cost expressed in R and is subtracted from
    every completed trade so validation can model spread/commission/slippage.

    Each signal is evaluated only on candles after the decision candle.
    The strategy's own ATR stop and 1:2 target define the outcome in R.
    If stop and target are both touched in the same future candle, the
    result is treated conservatively as a loss because candle ordering is
    unknown.
    """
    if len(candles) < warmup + horizon + 1:
        return {
            "status": "insufficient_data",
            "trades": 0,
            "message": f"Need at least {warmup + horizon + 1} candles",
        }

    trades = []
    i = warmup
    while i < len(candles) - horizon:
        signal = analyze(candles[:i + 1])
        action = signal.get("signal")
        if action not in ("BUY", "SELL"):
            i += 1
            continue

        entry = float(signal.get("entry") or candles[i].close)
        stop = signal.get("stop_loss")
        target = signal.get("take_profit")
        if stop is None or target is None:
            i += 1
            continue

        stop = float(stop)
        target = float(target)
        risk = abs(entry - stop)
        if risk <= 0:
            i += 1
            continue

        outcome = "OPEN"
        exit_index = None
        exit_price = None
        r_multiple = None
        ambiguous = False

        for j in range(i + 1, min(len(candles), i + horizon + 1)):
            bar = candles[j]
            if action == "BUY":
                hit_stop = bar.low <= stop
                hit_target = bar.high >= target
            else:
                hit_stop = bar.high >= stop
                hit_target = bar.low <= target

            if hit_stop and hit_target:
                outcome = "LOSS"
                exit_index = j
                exit_price = stop
                r_multiple = -1.0
                ambiguous = True
                break
            if hit_stop:
                outcome = "LOSS"
                exit_index = j
                exit_price = stop
                r_multiple = -1.0
                break
            if hit_target:
                outcome = "WIN"
                exit_index = j
                exit_price = target
                r_multiple = 2.0
                break

        if outcome == "OPEN":
            last = candles[min(len(candles) - 1, i + horizon)]
            exit_index = min(len(candles) - 1, i + horizon)
            exit_price = last.close
            move = (exit_price - entry) if action == "BUY" else (entry - exit_price)
            r_multiple = move / risk
            outcome = "TIMEOUT"

        r_multiple = float(r_multiple) - float(cost_r)

        trades.append({
            "index": i,
            "exit_index": exit_index,
            "signal": action,
            "entry": entry,
            "stop_loss": stop,
            "take_profit": target,
            "exit": round(float(exit_price), 8),
            "r": round(float(r_multiple), 4),
            "outcome": outcome,
            "ambiguous_bar": ambiguous,
        })

        # Do not stack overlapping positions in the validation pass.
        i = max(i + 1, (exit_index or i) + 1)

    if not trades:
        return {
            "status": "no_setups",
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "timeouts": 0,
            "win_rate": 0.0,
            "expectancy_r": 0.0,
            "profit_factor": 0.0,
            "max_drawdown_r": 0.0,
            "max_consecutive_losses": 0,
            "trades_sample": [],
        }

    wins = [t for t in trades if t["outcome"] == "WIN"]
    losses = [t for t in trades if t["outcome"] == "LOSS"]
    r_values = [float(t["r"]) for t in trades]
    gross_profit = sum(v for v in r_values if v > 0)
    gross_loss = abs(sum(v for v in r_values if v < 0))

    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    current_losses = 0
    max_consecutive_losses = 0
    for trade in trades:
        equity += float(trade["r"])
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
        if trade["outcome"] == "LOSS":
            current_losses += 1
            max_consecutive_losses = max(max_consecutive_losses, current_losses)
        else:
            current_losses = 0

    return {
        "status": "ok",
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "timeouts": sum(1 for t in trades if t["outcome"] == "TIMEOUT"),
        "ambiguous_bars": sum(1 for t in trades if t["ambiguous_bar"]),
        "win_rate": round((len(wins) / len(trades)) * 100, 2),
        "expectancy_r": round(sum(r_values) / len(r_values), 4),
        "total_r": round(sum(r_values), 4),
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else None,
        "max_drawdown_r": round(max_drawdown, 4),
        "max_consecutive_losses": max_consecutive_losses,
        "trades_sample": trades[-20:],
    }


def backtest_multi_timeframe(candles_1h, candles_15m, candles_5m, horizon=24, cost_r=0.0):
    """Walk forward through 5m decisions using only already-closed higher-TF bars.

    cost_r models fixed round-trip spread/commission/slippage in R.

    Higher-timeframe candles are selected by timestamp, so the validator does
    not leak future 15m/1h information into a 5m decision.
    """
    required = 200
    if min(len(candles_1h), len(candles_15m), len(candles_5m)) < required:
        return {
            "status": "insufficient_data",
            "trades": 0,
            "message": "Need at least 200 closed candles on every timeframe",
        }

    if any(c.time is None for c in candles_1h + candles_15m + candles_5m):
        return {
            "status": "missing_timestamps",
            "trades": 0,
            "message": "Historical candles must include timestamps for MTF validation",
        }

    def closed_before(candles, decision_time, duration_seconds):
        return [c for c in candles if int(c.time) + duration_seconds <= decision_time]

    trades = []
    i = required
    while i < len(candles_5m) - horizon:
        decision = candles_5m[i]
        decision_time = int(decision.time) + 300
        h1 = closed_before(candles_1h, decision_time, 3600)
        m15 = closed_before(candles_15m, decision_time, 900)
        if len(h1) < required or len(m15) < required:
            i += 1
            continue

        signal = analyze_multi_timeframe(h1, m15, candles_5m[:i + 1])
        action = signal.get("signal")
        if action not in ("BUY", "SELL"):
            i += 1
            continue

        entry = float(signal.get("entry") or decision.close)
        stop = signal.get("stop_loss")
        target = signal.get("take_profit")
        if stop is None or target is None:
            i += 1
            continue

        stop = float(stop)
        target = float(target)
        risk = abs(entry - stop)
        if risk <= 0:
            i += 1
            continue

        outcome = "OPEN"
        exit_index = None
        exit_price = None
        r_multiple = None
        ambiguous = False

        for j in range(i + 1, min(len(candles_5m), i + horizon + 1)):
            bar = candles_5m[j]
            if action == "BUY":
                hit_stop = bar.low <= stop
                hit_target = bar.high >= target
            else:
                hit_stop = bar.high >= stop
                hit_target = bar.low <= target

            if hit_stop and hit_target:
                outcome = "LOSS"
                exit_index = j
                exit_price = stop
                r_multiple = -1.0
                ambiguous = True
                break
            if hit_stop:
                outcome = "LOSS"
                exit_index = j
                exit_price = stop
                r_multiple = -1.0
                break
            if hit_target:
                outcome = "WIN"
                exit_index = j
                exit_price = target
                r_multiple = 2.0
                break

        if outcome == "OPEN":
            exit_index = min(len(candles_5m) - 1, i + horizon)
            exit_price = candles_5m[exit_index].close
            move = (exit_price - entry) if action == "BUY" else (entry - exit_price)
            r_multiple = move / risk
            outcome = "TIMEOUT"

        r_multiple = float(r_multiple) - float(cost_r)

        trades.append({
            "time": decision.time,
            "exit_time": candles_5m[exit_index].time if exit_index is not None else None,
            "signal": action,
            "entry": round(entry, 8),
            "stop_loss": round(stop, 8),
            "take_profit": round(target, 8),
            "exit": round(float(exit_price), 8),
            "r": round(float(r_multiple), 4),
            "outcome": outcome,
            "ambiguous_bar": ambiguous,
        })

        i = max(i + 1, (exit_index or i) + 1)

    if not trades:
        return {
            "status": "no_setups",
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "timeouts": 0,
            "win_rate": 0.0,
            "expectancy_r": 0.0,
            "profit_factor": 0.0,
            "max_drawdown_r": 0.0,
            "max_consecutive_losses": 0,
            "trades_sample": [],
        }

    r_values = [float(t["r"]) for t in trades]
    wins = [t for t in trades if t["outcome"] == "WIN"]
    losses = [t for t in trades if t["outcome"] == "LOSS"]
    gross_profit = sum(v for v in r_values if v > 0)
    gross_loss = abs(sum(v for v in r_values if v < 0))

    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    current_losses = 0
    max_consecutive_losses = 0
    for trade in trades:
        equity += float(trade["r"])
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
        if trade["outcome"] == "LOSS":
            current_losses += 1
            max_consecutive_losses = max(max_consecutive_losses, current_losses)
        else:
            current_losses = 0

    return {
        "status": "ok",
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "timeouts": sum(1 for t in trades if t["outcome"] == "TIMEOUT"),
        "ambiguous_bars": sum(1 for t in trades if t["ambiguous_bar"]),
        "win_rate": round(len(wins) / len(trades) * 100, 2),
        "expectancy_r": round(sum(r_values) / len(r_values), 4),
        "total_r": round(sum(r_values), 4),
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else None,
        "max_drawdown_r": round(max_drawdown, 4),
        "max_consecutive_losses": max_consecutive_losses,
        "trades_sample": trades[-20:],
    }



def macd(values, fast=12, slow=26, signal_period=9):
    """Return MACD line, signal line, and histogram."""
    if len(values) < slow + signal_period:
        return None
    line_values = []
    for i in range(slow - 1, len(values)):
        sample = values[:i + 1]
        line_values.append(ema(sample, fast) - ema(sample, slow))
    if len(line_values) < signal_period:
        return None
    signal_line = ema(line_values, signal_period)
    line = line_values[-1]
    return {"line": line, "signal": signal_line, "histogram": line - signal_line}


def supertrend(candles, period=10, multiplier=3.0):
    """ATR-based trend direction, unavailable until enough bars exist."""
    if len(candles) < period + 2:
        return None
    final_upper = final_lower = None
    direction = 1
    line = None
    for i in range(len(candles)):
        if i + 1 < period:
            continue
        window = candles[max(0, i - period + 1):i + 1]
        mid = (candles[i].high + candles[i].low) / 2.0
        av = atr(window, period)
        upper, lower = mid + multiplier * av, mid - multiplier * av
        if final_upper is None:
            final_upper, final_lower = upper, lower
        else:
            previous_close = candles[i - 1].close
            final_upper = upper if upper < final_upper or previous_close > final_upper else final_upper
            final_lower = lower if lower > final_lower or previous_close < final_lower else final_lower
            if direction == -1 and candles[i].close > final_upper:
                direction = 1
            elif direction == 1 and candles[i].close < final_lower:
                direction = -1
        line = final_lower if direction == 1 else final_upper
    return {"direction": "BUY" if direction == 1 else "SELL", "line": float(line)} if line is not None else None


def chandelier_exit(candles, period=22, multiplier=3.0):
    """Return ATR-based long/short trailing exit levels."""
    if len(candles) < period:
        return None
    window = candles[-period:]
    av = atr(candles, min(14, len(candles)))
    if av <= 0:
        return None
    return {"long_exit": max(c.high for c in window) - multiplier * av,
            "short_exit": min(c.low for c in window) + multiplier * av}


def analyze_selected_strategy(candles_1h, candles_15m, candles_5m, strategy="institutional"):
    """Run only the strategy selected in the user's saved bot configuration."""
    if strategy == "institutional":
        return analyze_multi_timeframe(candles_1h, candles_15m, candles_5m)

    candles = candles_5m
    if len(candles) < 30:
        return {"signal":"NO TRADE","score":0,"reason":"Insufficient history for selected strategy"}

    closes = [c.close for c in candles]
    current = float(closes[-1])
    av = atr(candles)
    pattern = candle_structure(candles)
    rv = rsi(closes)
    recent = candles[-21:-1]
    if not recent or av <= 0 or current <= 0:
        return {"signal":"NO TRADE","score":0,"reason":"Invalid market data for selected strategy"}

    side = None
    score = 0
    reason = ""
    if strategy == "reversal":
        bullish_reversal = rv <= 32 and pattern["bullish"] and pattern["strength"] >= 0.75
        bearish_reversal = rv >= 68 and pattern["bearish"] and pattern["strength"] >= 0.75
        if bullish_reversal:
            side, score = "BUY", min(95, 65 + int((32-rv)*2))
            reason = f"Reversal setup: oversold RSI ({rv:.1f}) with {pattern['pattern']}"
        elif bearish_reversal:
            side, score = "SELL", min(95, 65 + int((rv-68)*2))
            reason = f"Reversal setup: overbought RSI ({rv:.1f}) with {pattern['pattern']}"
        else:
            reason = f"No confirmed reversal: RSI {rv:.1f}, {pattern['pattern']}"
    elif strategy == "breakout":
        resistance = max(float(c.high) for c in recent)
        support = min(float(c.low) for c in recent)
        last = candles[-1]
        body_ratio = pattern.get("body_ratio", 0)
        if current > resistance and last.close > last.open and body_ratio >= 0.5:
            side, score = "BUY", min(95, 70 + int(body_ratio*20))
            reason = "Breakout confirmed above recent resistance with bullish candle"
        elif current < support and last.close < last.open and body_ratio >= 0.5:
            side, score = "SELL", min(95, 70 + int(body_ratio*20))
            reason = "Breakout confirmed below recent support with bearish candle"
        else:
            reason = "No confirmed close beyond recent support/resistance"
    else:
        return {"signal":"NO TRADE","score":0,"reason":"Unknown strategy; execution blocked"}

    macd_state = macd(closes)
    trend_state = supertrend(candles)
    chandelier = chandelier_exit(candles)
    # Breakouts must agree with ATR trend and momentum; reversal setups use
    # the explicit RSI extreme + strong candle rule above.
    if side is not None and strategy == "breakout":
        macd_aligned = bool(macd_state and (
            (side == "BUY" and macd_state["line"] > macd_state["signal"] and macd_state["histogram"] > 0)
            or (side == "SELL" and macd_state["line"] < macd_state["signal"] and macd_state["histogram"] < 0)
        ))
        trend_aligned = bool(trend_state and trend_state["direction"] == side)
        if not macd_aligned or not trend_aligned:
            reason += f" · blocked by confirmation filter (Supertrend={trend_state['direction'] if trend_state else 'insufficient'}, MACD={'aligned' if macd_aligned else 'not aligned'})"
            side = None
            score = min(score, 60)
    if side is None:
        return {
            "signal":"NO TRADE", "score":score, "reason":reason, "strategy":strategy,
            "indicators":{"rsi":rv,"atr":av,"pattern":pattern["pattern"],"macd":macd_state,"supertrend":trend_state},
        }
    entry = current
    stop = entry - av*1.5 if side == "BUY" else entry + av*1.5
    # Tighten only; never widen the initial ATR risk with the Chandelier level.
    if chandelier:
        candidate = chandelier["long_exit"] if side == "BUY" else chandelier["short_exit"]
        if side == "BUY" and entry > candidate > stop:
            stop = candidate
        elif side == "SELL" and entry < candidate < stop:
            stop = candidate
    target = entry + (entry-stop)*2 if side == "BUY" else entry - (stop-entry)*2
    return {
        "signal":side, "score":score, "reason":reason, "entry":round(entry,8),
        "stop_loss":round(stop,8), "take_profit":round(target,8),
        "strategy":strategy,
        "indicators":{"rsi":rv,"atr":av,"pattern":pattern["pattern"],"macd":macd_state,"supertrend":trend_state,"chandelier_exit":chandelier},
        "timeframes":{"1h":"context","15m":"setup","5m":"trigger"},
    }
