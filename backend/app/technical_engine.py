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

def deep_market_analysis(candles_1h,candles_15m,candles_5m):
    h1=analyze(candles_1h);m15=analyze(candles_15m);m5=analyze(candles_5m)
    dirs=[h1.get("direction"),m15.get("direction"),m5.get("direction")]
    aligned=dirs[0] in ("BULLISH","BEARISH") and dirs[0]==dirs[1]==dirs[2]
    total=int(h1.get("confluence",0)*0.35+m15.get("confluence",0)*0.35+m5.get("confluence",0)*0.30)
    higher_tf_ok=h1.get("confluence",0)>=55 and m15.get("confluence",0)>=55
    entry_tf_ok=m5.get("decision")=="TRADE CANDIDATE"
    decision="TRADE CANDIDATE" if aligned and higher_tf_ok and entry_tf_ok and total>=70 else "WAIT"
    if not aligned or total<50: decision="NO TRADE"
    reasons=[]
    if not aligned: reasons.append(f"Multi-timeframe indicator direction is not aligned: 1H {dirs[0]}, 15M {dirs[1]}, 5M {dirs[2]}.")
    reasons.extend(h1.get("reasons",[])[:2]);reasons.extend(m15.get("reasons",[])[:2]);reasons.extend(m5.get("reasons",[])[:2])
    return {"decision":decision,"confluence":total,"timeframes":{"1h":h1,"15m":m15,"5m":m5},"reasons":reasons[:10],
            "research_note":"Technical evidence is probabilistic. News/fundamental risk must be checked separately before execution."}
