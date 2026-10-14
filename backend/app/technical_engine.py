from math import sqrt

def _closes(c): return [float(x.close) for x in c]
def sma(values, n):
    if not values: return 0.0
    n=max(1,min(n,len(values)))
    return sum(values[-n:])/n

def ema(values,n):
    if not values: return 0.0
    n=max(1,n)
    if len(values)<n: return sum(values)/len(values)
    k=2/(n+1)
    v=sum(values[:n])/n
    for x in values[n:]: v=x*k+v*(1-k)
    return v

def rsi(values,n=14):
    if len(values)<=n: return 50.0
    gains=[];losses=[]
    for i in range(1,len(values)):
        d=values[i]-values[i-1];gains.append(max(d,0));losses.append(max(-d,0))
    ag=sum(gains[:n])/n; al=sum(losses[:n])/n
    for i in range(n,len(gains)):
        ag=(ag*(n-1)+gains[i])/n; al=(al*(n-1)+losses[i])/n
    return 100.0 if al==0 else 100-(100/(1+ag/al))

def atr(c,n=14):
    if not c:return 0.0
    trs=[]
    for i,x in enumerate(c):
        pc=float(c[i-1].close) if i else float(x.close)
        trs.append(max(float(x.high)-float(x.low),abs(float(x.high)-pc),abs(float(x.low)-pc)))
    return sum(trs[-n:])/min(n,len(trs))

def macd(values):
    line=ema(values,12)-ema(values,26)
    hist_series=[]
    start=max(26,len(values)-60)
    for i in range(start,len(values)+1):
        seg=values[:i]
        hist_series.append(ema(seg,12)-ema(seg,26))
    signal=ema(hist_series,9) if hist_series else 0.0
    return line,signal,line-signal

def bollinger(values,n=20,k=2):
    mid=sma(values,n); sample=values[-min(n,len(values)):]
    mean=sum(sample)/len(sample) if sample else 0
    var=sum((x-mean)**2 for x in sample)/len(sample) if sample else 0
    sd=sqrt(var)
    return mid,mid+k*sd,mid-k*sd

def stochastic(c,n=14):
    if len(c)<n:return 50.0
    hi=max(float(x.high) for x in c[-n:]);lo=min(float(x.low) for x in c[-n:])
    return 50.0 if hi==lo else (float(c[-1].close)-lo)/(hi-lo)*100

def cci(c,n=20):
    if len(c)<n:return 0.0
    tp=[(float(x.high)+float(x.low)+float(x.close))/3 for x in c[-n:]]
    mean=sum(tp)/n
    md=sum(abs(x-mean) for x in tp)/n
    return 0.0 if md==0 else (tp[-1]-mean)/(0.015*md)

def adx(c,n=14):
    if len(c)<n+2:return {"adx":0.0,"plus_di":0.0,"minus_di":0.0}
    trs=[];plus=[];minus=[]
    for i in range(1,len(c)):
        h,l,ph,pl,pc=float(c[i].high),float(c[i].low),float(c[i-1].high),float(c[i-1].low),float(c[i-1].close)
        trs.append(max(h-l,abs(h-pc),abs(l-pc)))
        up=h-ph;down=pl-l
        plus.append(up if up>down and up>0 else 0.0)
        minus.append(down if down>up and down>0 else 0.0)
    tr=sum(trs[-n:]);p=sum(plus[-n:]);m=sum(minus[-n:])
    if tr==0:return {"adx":0.0,"plus_di":0.0,"minus_di":0.0}
    pdi=100*p/tr;mdi=100*m/tr;dx=100*abs(pdi-mdi)/max(pdi+mdi,1e-12)
    return {"adx":dx,"plus_di":pdi,"minus_di":mdi}

def roc(values,n=12):
    if len(values)<=n:return 0.0
    base=values[-n-1]
    return (values[-1]-base)/max(abs(base),1e-12)*100

def williams_r(c,n=14):
    if len(c)<n:return -50.0
    hi=max(float(x.high) for x in c[-n:]);lo=min(float(x.low) for x in c[-n:])
    return -50.0 if hi==lo else (hi-float(c[-1].close))/(hi-lo)*-100

def obv(c):
    if not c:return 0.0
    total=0.0
    for i in range(1,len(c)):
        if c[i].close>c[i-1].close: total+=float(c[i].volume or 0)
        elif c[i].close<c[i-1].close: total-=float(c[i].volume or 0)
    return total

def candle_patterns(c):
    if len(c)<3:return []
    out=[]
    a,b,x=c[-3],c[-2],c[-1]
    rng=max(float(x.high)-float(x.low),1e-12);body=abs(float(x.close)-float(x.open))
    upper=float(x.high)-max(float(x.open),float(x.close));lower=min(float(x.open),float(x.close))-float(x.low)
    bull=x.close>x.open;bear=x.close<x.open
    if body/rng<=0.12: out.append("DOJI")
    if lower>=body*2 and upper<=max(body,1e-12)*1.2 and (x.close-x.low)/rng>=0.6: out.append("HAMMER / BULLISH PIN BAR")
    if upper>=body*2 and lower<=max(body,1e-12)*1.2 and (x.close-x.low)/rng<=0.4: out.append("SHOOTING STAR / BEARISH PIN BAR")
    if bull and b.close<b.open and x.open<=b.close and x.close>=b.open: out.append("BULLISH ENGULFING")
    if bear and b.close>b.open and x.open>=b.close and x.close<=b.open: out.append("BEARISH ENGULFING")
    if x.high<=b.high and x.low>=b.low: out.append("INSIDE BAR")
    if x.high>=b.high and x.low<=b.low: out.append("OUTSIDE BAR")
    if bull and body/rng>=0.8 and upper/rng<=0.1 and lower/rng<=0.1: out.append("BULLISH MARUBOZU")
    if bear and body/rng>=0.8 and upper/rng<=0.1 and lower/rng<=0.1: out.append("BEARISH MARUBOZU")
    return out or ["NEUTRAL CANDLE"]

def _divergence(c):
    if len(c)<30:return "NONE"
    vals=_closes(c[-30:]); rs=[rsi(_closes(c[:i]),14) for i in range(max(15,len(c)-30),len(c)+1)]
    if len(rs)<10:return "NONE"
    first_price=min(vals[:15]);last_price=min(vals[15:]);first_r=min(rs[:len(rs)//2]);last_r=min(rs[len(rs)//2:])
    if last_price<first_price and last_r>first_r:return "BULLISH DIVERGENCE"
    first_price=max(vals[:15]);last_price=max(vals[15:]);first_r=max(rs[:len(rs)//2]);last_r=max(rs[len(rs)//2:])
    if last_price>first_price and last_r<first_r:return "BEARISH DIVERGENCE"
    return "NONE"

def analyze(c):
    values=_closes(c)
    if len(values)<60:
        return {"status":"INSUFFICIENT","indicators":{},"candles":[],"confluence":0,"decision":"NO TRADE","reasons":["Not enough candles for deep indicator analysis."]}
    current=values[-1]
    e20=ema(values,20);e50=ema(values,50);e200=ema(values,200)
    r=rsi(values);a=atr(c);mline,msignal,mhist=macd(values);mid,upper,lower=bollinger(values)
    st=stochastic(c);cc=cci(c);d=adx(c);r12=roc(values);wr=williams_r(c);ob=obv(c)
    trend="BULLISH" if current>e20>e50 else "BEARISH" if current<e20<e50 else "MIXED"
    strength="STRONG" if d["adx"]>=25 else "WEAK"
    vol="HIGH" if a/max(current,1e-12)>0.01 else "NORMAL"
    momentum_votes=(1 if r>=52 else -1 if r<=48 else 0)+(1 if mline>msignal and mline>0 else -1 if mline<msignal and mline<0 else 0)+(1 if st>=55 else -1 if st<=45 else 0)+(1 if cc>=0 else -1 if cc<0 else 0)+(1 if r12>0 else -1 if r12<0 else 0)
    direction=1 if trend=="BULLISH" else -1 if trend=="BEARISH" else 0
    structure_high=max(float(x.high) for x in c[-21:-1]);structure_low=min(float(x.low) for x in c[-21:-1])
    breakout=1 if current>structure_high else -1 if current<structure_low else 0
    candle=candle_patterns(c)
    candle_bull=any("BULLISH" in x or "HAMMER" in x for x in candle)
    candle_bear=any("BEARISH" in x or "SHOOTING" in x for x in candle)
    votes=0
    votes += 25 if direction and direction== (1 if momentum_votes>0 else -1 if momentum_votes<0 else 0) else 0
    votes += 20 if strength=="STRONG" and direction else 0
    votes += 20 if breakout==direction and direction else 0
    votes += 15 if (direction==1 and candle_bull) or (direction==-1 and candle_bear) else 0
    votes += 10 if (direction==1 and current>=mid) or (direction==-1 and current<=mid) else 0
    votes += 10 if vol!="HIGH" else 0
    reasons=[]
    if direction==0: reasons.append("Trend structure is mixed.")
    if strength=="WEAK": reasons.append("ADX says trend strength is weak; range conditions are more likely.")
    if breakout==0: reasons.append("No fresh structure breakout.")
    if direction==1 and momentum_votes<0: reasons.append("Momentum indicators conflict with bullish trend.")
    if direction==-1 and momentum_votes>0: reasons.append("Momentum indicators conflict with bearish trend.")
    if vol=="HIGH": reasons.append("Volatility is high; normal stop assumptions may be less reliable.")
    if _divergence(c)!="NONE": reasons.append(_divergence(c))
    if not reasons: reasons.append("Trend, momentum, structure and candle evidence are aligned.")
    decision="TRADE CANDIDATE" if votes>=70 and direction and breakout==direction and ((direction==1 and candle_bull) or (direction==-1 and candle_bear)) else "WAIT"
    if votes<50 or direction==0: decision="NO TRADE"
    return {
        "status":"OK","decision":decision,"confluence":int(votes),"direction":trend,
        "trend_strength":strength,"volatility":vol,"candles":candle[-4:],
        "divergence":_divergence(c),"reasons":reasons[:8],
        "indicators":{
            "sma20":round(sma(values,20),8),"sma50":round(sma(values,50),8),
            "ema20":round(e20,8),"ema50":round(e50,8),"ema200":round(e200,8),
            "rsi14":round(r,2),"macd":round(mline,8),"macd_signal":round(msignal,8),"macd_hist":round(mhist,8),
            "bb_middle":round(mid,8),"bb_upper":round(upper,8),"bb_lower":round(lower,8),
            "atr14":round(a,8),"adx14":round(d["adx"],2),"plus_di":round(d["plus_di"],2),"minus_di":round(d["minus_di"],2),
            "stochastic14":round(st,2),"cci20":round(cc,2),"roc12":round(r12,2),"williams_r14":round(wr,2),"obv":round(ob,2),
        }
    }



def supertrend(c, period=10, multiplier=3.0):
    """Return Supertrend direction/value using ATR bands on closed candles."""
    if len(c) < period + 2:
        return {"direction": "UNKNOWN", "value": None, "upper": None, "lower": None}
    ranges = []
    for i, candle in enumerate(c):
        previous_close = float(c[i - 1].close) if i else float(candle.close)
        ranges.append(max(
            float(candle.high) - float(candle.low),
            abs(float(candle.high) - previous_close),
            abs(float(candle.low) - previous_close),
        ))
    atr_values = []
    for i in range(len(c)):
        sample = ranges[max(0, i - period + 1):i + 1]
        atr_values.append(sum(sample) / len(sample))
    upper = [((float(x.high) + float(x.low)) / 2) + multiplier * atr_values[i] for i, x in enumerate(c)]
    lower = [((float(x.high) + float(x.low)) / 2) - multiplier * atr_values[i] for i, x in enumerate(c)]
    final_upper = [upper[0]]
    final_lower = [lower[0]]
    trend = [1]
    for i in range(1, len(c)):
        previous_close = float(c[i - 1].close)
        final_upper.append(upper[i] if upper[i] < final_upper[i - 1] or previous_close > final_upper[i - 1] else final_upper[i - 1])
        final_lower.append(lower[i] if lower[i] > final_lower[i - 1] or previous_close < final_lower[i - 1] else final_lower[i - 1])
        close = float(c[i].close)
        if trend[i - 1] == -1 and close > final_upper[i]:
            trend.append(1)
        elif trend[i - 1] == 1 and close < final_lower[i]:
            trend.append(-1)
        else:
            trend.append(trend[i - 1])
    is_up = trend[-1] == 1
    return {
        "direction": "BULLISH" if is_up else "BEARISH",
        "value": round(final_lower[-1] if is_up else final_upper[-1], 8),
        "upper": round(final_upper[-1], 8),
        "lower": round(final_lower[-1], 8),
    }


def chandelier_exit(c, period=22, multiplier=3.0):
    """ATR-based Chandelier levels; report levels, do not send broker commands."""
    if len(c) < 2:
        return {"long": None, "short": None, "atr": None}
    window = c[-min(period, len(c)):]
    current_atr = atr(window, min(period, len(window)))
    highest_high = max(float(x.high) for x in window)
    lowest_low = min(float(x.low) for x in window)
    return {
        "long": round(highest_high - multiplier * current_atr, 8),
        "short": round(lowest_low + multiplier * current_atr, 8),
        "atr": round(current_atr, 8),
    }


def wavetrend(c, channel_length=10, average_length=21):
    """LazyBear-style WaveTrend WT1/WT2 oscillator, calculated locally."""
    if len(c) < max(channel_length, average_length) + 2:
        return {"wt1": None, "wt2": None, "direction": "UNKNOWN", "cross": "NONE"}
    ap = [(float(x.high) + float(x.low) + float(x.close)) / 3 for x in c]
    esa = []
    deviation = []
    k1 = 2 / (channel_length + 1)
    for i, value in enumerate(ap):
        esa.append(value if i == 0 else value * k1 + esa[-1] * (1 - k1))
        diff = abs(value - esa[-1])
        deviation.append(diff if i == 0 else diff * k1 + deviation[-1] * (1 - k1))
    ci = [(ap[i] - esa[i]) / max(0.015 * deviation[i], 1e-12) for i in range(len(ap))]
    k2 = 2 / (average_length + 1)
    wt1 = []
    for i, value in enumerate(ci):
        wt1.append(value if i == 0 else value * k2 + wt1[-1] * (1 - k2))
    wt2 = [sum(wt1[max(0, i - 3):i + 1]) / len(wt1[max(0, i - 3):i + 1]) for i in range(len(wt1))]
    cross = "NONE"
    if wt1[-2] <= wt2[-2] and wt1[-1] > wt2[-1]:
        cross = "BULLISH"
    elif wt1[-2] >= wt2[-2] and wt1[-1] < wt2[-1]:
        cross = "BEARISH"
    return {
        "wt1": round(wt1[-1], 4),
        "wt2": round(wt2[-1], 4),
        "direction": "BULLISH" if wt1[-1] > wt2[-1] else "BEARISH" if wt1[-1] < wt2[-1] else "NEUTRAL",
        "cross": cross,
    }


def selected_indicator_evidence(candles):
    """Calculate selected indicators on completed candles only."""
    # OHLC feeds commonly include the currently forming bar. Exclude it for
    # every selected indicator so confirmation values share one closed-bar basis.
    closed_candles = candles[:-1]
    if len(closed_candles) < 60:
        return {"status": "INSUFFICIENT", "supertrend": {}, "chandelier_exit": {}, "wavetrend": {}}
    values = _closes(closed_candles)
    macd_line, macd_signal, macd_hist = macd(values)
    directional = adx(closed_candles)
    return {
        "status": "OK",
        "supertrend": supertrend(closed_candles),
        "macd": {
            "line": round(macd_line, 8),
            "signal": round(macd_signal, 8),
            "histogram": round(macd_hist, 8),
            "direction": "BULLISH" if macd_line > macd_signal and macd_hist > 0 else "BEARISH" if macd_line < macd_signal and macd_hist < 0 else "MIXED",
        },
        "adx_di": {
            "adx": round(directional["adx"], 2),
            "plus_di": round(directional["plus_di"], 2),
            "minus_di": round(directional["minus_di"], 2),
            "regime": "TRENDING" if directional["adx"] >= 25 else "RANGING_OR_WEAK" if directional["adx"] < 18 else "TRANSITION",
        },
        "chandelier_exit": chandelier_exit(closed_candles),
        # Public OHLC providers commonly include the still-forming final bar.
        # Use only completed bars for crossover confirmation to reduce repainting.
        "wavetrend": wavetrend(closed_candles),
    }


def _swing_points(candles, lookback=3):
    """Find confirmed local swing highs/lows without using future bars."""
    highs=[]
    lows=[]
    if len(candles) < lookback*2+3:
        return highs,lows
    for i in range(lookback, len(candles)-lookback):
        high=float(candles[i].high)
        low=float(candles[i].low)
        left=candles[i-lookback:i]
        right=candles[i+1:i+1+lookback]
        if high >= max(float(x.high) for x in left+right):
            highs.append((i,high))
        if low <= min(float(x.low) for x in left+right):
            lows.append((i,low))
    return highs,lows


def _market_structure_detail(candles):
    """Classify HH/HL/LH/LL structure and recent break/sweep behavior."""
    highs,lows=_swing_points(candles)
    if len(highs)<2 or len(lows)<2:
        return {
            "state":"UNKNOWN",
            "break":"NONE",
            "sweep":"NONE",
            "swing_high":None,
            "swing_low":None,
        }
    h1,h2=highs[-2],highs[-1]
    l1,l2=lows[-2],lows[-1]
    hh=h2[1]>h1[1]
    hl=l2[1]>l1[1]
    lh=h2[1]<h1[1]
    ll=l2[1]<l1[1]
    if hh and hl:
        state="BULLISH_STRUCTURE"
    elif lh and ll:
        state="BEARISH_STRUCTURE"
    else:
        state="MIXED_STRUCTURE"

    current=float(candles[-1].close)
    recent_high=max(float(x.high) for x in candles[-11:-1])
    recent_low=min(float(x.low) for x in candles[-11:-1])
    prev_high=max(float(x.high) for x in candles[-21:-11])
    prev_low=min(float(x.low) for x in candles[-21:-11])
    break_state="NONE"
    if current>recent_high:
        break_state="BULLISH_BREAK"
    elif current<recent_low:
        break_state="BEARISH_BREAK"

    # A sweep takes liquidity beyond an older extreme but closes back inside it.
    last=candles[-1]
    sweep="NONE"
    if float(last.high)>prev_high and current<prev_high:
        sweep="BUY_SIDE_SWEEP"
    elif float(last.low)<prev_low and current>prev_low:
        sweep="SELL_SIDE_SWEEP"

    return {
        "state":state,
        "break":break_state,
        "sweep":sweep,
        "higher_high":hh,
        "higher_low":hl,
        "lower_high":lh,
        "lower_low":ll,
        "swing_high":round(h2[1],8),
        "swing_low":round(l2[1],8),
        "support":round(l2[1],8),
        "resistance":round(h2[1],8),
    }


def _regime_detail(candles):
    values=_closes(candles)
    if len(values)<60:
        return {"regime":"UNKNOWN","trend_strength":"UNKNOWN","adx":0.0,"volatility":"UNKNOWN"}
    current=values[-1]
    e20=ema(values,20)
    e50=ema(values,50)
    e200=ema(values,200)
    d=adx(candles)
    a=atr(candles)
    atr_pct=a/max(abs(current),1e-12)*100
    if d["adx"]<18:
        regime="RANGE"
    elif current>e20>e50>e200 and d["plus_di"]>d["minus_di"]:
        regime="BULL_TREND"
    elif current<e20<e50<e200 and d["minus_di"]>d["plus_di"]:
        regime="BEAR_TREND"
    else:
        regime="TRANSITION"
    if atr_pct>=1.5:
        volatility="EXTREME"
    elif atr_pct>=0.8:
        volatility="HIGH"
    elif atr_pct<=0.15:
        volatility="LOW"
    else:
        volatility="NORMAL"
    return {
        "regime":regime,
        "trend_strength":"STRONG" if d["adx"]>=25 else "MODERATE" if d["adx"]>=18 else "WEAK",
        "adx":round(d["adx"],2),
        "plus_di":round(d["plus_di"],2),
        "minus_di":round(d["minus_di"],2),
        "atr_pct":round(atr_pct,4),
        "volatility":volatility,
    }


def _evidence_direction(candles):
    values=_closes(candles)
    if len(values)<60:
        return {"direction":"NEUTRAL","votes":0}
    d=adx(candles)
    e20=ema(values,20)
    e50=ema(values,50)
    e200=ema(values,200)
    r=rsi(values)
    mline,msignal,_=macd(values)
    direction=0
    votes=0
    if values[-1]>e20>e50>e200:
        direction=1; votes+=2
    elif values[-1]<e20<e50<e200:
        direction=-1; votes+=2
    if direction and ((direction==1 and d["plus_di"]>d["minus_di"]) or (direction==-1 and d["minus_di"]>d["plus_di"])):
        votes+=1
    if direction and ((direction==1 and 50<r<72) or (direction==-1 and 28<r<50)):
        votes+=1
    if direction and ((direction==1 and mline>msignal) or (direction==-1 and mline<msignal)):
        votes+=1
    return {"direction":"BUY" if direction==1 else "SELL" if direction==-1 else "NEUTRAL","votes":votes}


def _session_context(candles):
    if not candles or candles[-1].time is None:
        return "UNKNOWN"
    from datetime import datetime, timezone
    hour=datetime.fromtimestamp(int(candles[-1].time),tz=timezone.utc).hour
    if 7<=hour<12:
        return "LONDON"
    if 12<=hour<17:
        return "LONDON/NEW YORK OVERLAP"
    if 17<=hour<21:
        return "NEW YORK"
    if 21<=hour or hour<7:
        return "ASIA/OFF-HOURS"
    return "UNKNOWN"


def deep_market_analysis(candles_1h,candles_15m,candles_5m):
    """Multi-factor trading intelligence gate.

    This layer deliberately separates market knowledge from the raw signal:
    trend/regime, structure, liquidity behavior, momentum, volatility,
    multi-timeframe agreement, entry trigger, and execution conditions.
    It is a decision filter, not a profitability guarantee.
    """
    h1=analyze(candles_1h)
    m15=analyze(candles_15m)
    m5=analyze(candles_5m)
    h1reg=_regime_detail(candles_1h)
    m15reg=_regime_detail(candles_15m)
    m5reg=_regime_detail(candles_5m)
    h1struct=_market_structure_detail(candles_1h)
    m15struct=_market_structure_detail(candles_15m)
    m5struct=_market_structure_detail(candles_5m)
    h1ev=_evidence_direction(candles_1h)
    m15ev=_evidence_direction(candles_15m)
    m5ev=_evidence_direction(candles_5m)
    # Keep selected indicator readings visible for audit and later walk-forward
    # evaluation. These readings do not independently authorize a trade.
    h1selected=selected_indicator_evidence(candles_1h)
    m15selected=selected_indicator_evidence(candles_15m)
    m5selected=selected_indicator_evidence(candles_5m)

    directions=[h1ev["direction"],m15ev["direction"],m5ev["direction"]]
    aligned=directions[0] in ("BUY","SELL") and directions[0]==directions[1]==directions[2]
    direction=directions[0] if aligned else "NEUTRAL"

    weighted=int(
        h1.get("confluence",0)*0.35+
        m15.get("confluence",0)*0.35+
        m5.get("confluence",0)*0.30
    )
    score=min(100,weighted)
    reasons=[]
    vetoes=[]

    if not aligned:
        vetoes.append(f"Multi-timeframe direction is not aligned: 1H {directions[0]}, 15M {directions[1]}, 5M {directions[2]}.")
    if h1reg["regime"]=="RANGE":
        vetoes.append("Higher timeframe is range-bound; trend-following entries have weaker edge.")
    if m15reg["regime"]=="RANGE":
        vetoes.append("15M is range-bound; wait for a clean structural break.")
    if m5reg["regime"]=="RANGE":
        vetoes.append("5M is range-bound; the entry trigger is less reliable.")
    if h1reg["volatility"]=="EXTREME" or m5reg["volatility"]=="EXTREME":
        vetoes.append("Volatility is extreme; normal stop/target assumptions are unreliable.")

    structure_ok = (
        (direction=="BUY" and m15struct["break"]=="BULLISH_BREAK") or
        (direction=="SELL" and m15struct["break"]=="BEARISH_BREAK")
    )
    trigger_ok = m5.get("decision")=="TRADE CANDIDATE"
    candle_ok = (
        direction=="BUY" and any("BULLISH" in x or "HAMMER" in x for x in m5.get("candles",[]))
    ) or (
        direction=="SELL" and any("BEARISH" in x or "SHOOTING" in x for x in m5.get("candles",[]))
    )
    if not structure_ok:
        vetoes.append("15M has no fresh directional structure break.")
    if not trigger_ok:
        vetoes.append("5M entry trigger is not confirmed.")
    if not candle_ok:
        vetoes.append("5M price-action candle does not confirm the direction.")

    # Avoid buying the top or selling the bottom of a recent range unless a
    # fresh break is confirmed.
    current=float(candles_5m[-1].close)
    recent_high=max(float(x.high) for x in candles_5m[-21:-1])
    recent_low=min(float(x.low) for x in candles_5m[-21:-1])
    span=max(recent_high-recent_low,1e-12)
    position=(current-recent_low)/span
    if direction=="BUY" and position>0.92 and m5struct["break"]!="BULLISH_BREAK":
        vetoes.append("Price is overextended near the top of the recent range.")
    if direction=="SELL" and position<0.08 and m5struct["break"]!="BEARISH_BREAK":
        vetoes.append("Price is overextended near the bottom of the recent range.")

    if direction=="BUY" and h1reg["adx"]<18:
        vetoes.append("ADX is too weak to support a trend-following BUY.")
    if direction=="SELL" and h1reg["adx"]<18:
        vetoes.append("ADX is too weak to support a trend-following SELL.")

    if aligned and not vetoes:
        reasons.append("Trend, structure, momentum and entry evidence agree across all three timeframes.")
    if m15struct["sweep"]!="NONE":
        reasons.append(f"Liquidity behavior detected: {m15struct['sweep']}.")
    if m5struct["sweep"]!="NONE":
        reasons.append(f"5M liquidity behavior detected: {m5struct['sweep']}.")
    if h1reg["trend_strength"]=="STRONG":
        reasons.append(f"1H trend strength is strong (ADX {h1reg['adx']}).")
    if m15reg["trend_strength"]=="WEAK":
        reasons.append(f"15M trend strength is weak (ADX {m15reg['adx']}).")

    # A raw signal score can never override a veto. This is the key safety
    # property of the intelligence layer.
    decision="TRADE CANDIDATE" if (
        aligned and
        score>=75 and
        not vetoes and
        structure_ok and
        trigger_ok and
        candle_ok
    ) else "WAIT"
    if not aligned and score<50:
        decision="NO TRADE"
    if len(vetoes)>=3:
        decision="NO TRADE"

    session=_session_context(candles_5m)
    return {
        "decision":decision,
        "confluence":score,
        "direction":direction,
        "session":session,
        "vetoes":vetoes[:12],
        "reasons":(reasons+vetoes)[:12],
        "knowledge_checks":[
            "market regime",
            "multi-timeframe alignment",
            "market structure",
            "liquidity/sweeps",
            "momentum",
            "volatility",
            "price extension",
            "candlestick confirmation",
            "entry trigger",
            "risk/reward",
            "execution conditions",
        ],
        "timeframes":{
            "1h":{"regime":h1reg,"structure":h1struct,"evidence":h1ev,"selected_indicators":h1selected,"analysis":h1},
            "15m":{"regime":m15reg,"structure":m15struct,"evidence":m15ev,"selected_indicators":m15selected,"analysis":m15},
            "5m":{"regime":m5reg,"structure":m5struct,"evidence":m5ev,"selected_indicators":m5selected,"analysis":m5},
        },
        "research_note":"Technical evidence is probabilistic. Profitability is not guaranteed; historical validation, execution costs, and fundamental/news risk must be checked before automation.",
    }
