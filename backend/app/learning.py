"""Live trade feedback and strategy health for TradeGuard."""
from __future__ import annotations
from .db import connection
import time

_GATE_CACHE={}
_GATE_CACHE_TTL=60

def _metrics(rows):
    rs=[float(r[0] or 0) for r in rows]
    if not rs:
        return {"trades":0,"wins":0,"losses":0,"win_rate":0.0,"expectancy_r":0.0,"profit_factor":None,"total_r":0.0,"max_drawdown_r":0.0}
    wins=sum(1 for r in rs if r>0)
    losses=sum(1 for r in rs if r<0)
    gross_win=sum(r for r in rs if r>0)
    gross_loss=abs(sum(r for r in rs if r<0))
    equity=peak=drawdown=0.0
    for r in rs:
        equity+=r
        peak=max(peak,equity)
        drawdown=max(drawdown,peak-equity)
    return {"trades":len(rs),"wins":wins,"losses":losses,"win_rate":round(wins/len(rs)*100,2),
            "expectancy_r":round(sum(rs)/len(rs),4),
            "profit_factor":round(gross_win/gross_loss,4) if gross_loss>0 else None,
            "total_r":round(sum(rs),4),"max_drawdown_r":round(drawdown,4)}


def performance_snapshot(user_id, symbol=None, setup=None, session=None, regime=None, limit=50):
    clauses=["user_id=%s","r_multiple IS NOT NULL","closed_at IS NOT NULL"]; args=[user_id]
    if symbol: clauses.append("UPPER(symbol)=UPPER(%s)"); args.append(symbol)
    if setup: clauses.append("COALESCE(context->>'setup',setup)=%s"); args.append(setup)
    if session: clauses.append("context->>'session'=%s"); args.append(session)
    if regime: clauses.append("context->>'regime'=%s"); args.append(regime)
    args.append(max(1,min(int(limit),200)))
    with connection() as conn:
        rows=conn.execute("SELECT r_multiple FROM trade_journal WHERE "+" AND ".join(clauses)+" ORDER BY closed_at DESC LIMIT %s",tuple(args)).fetchall()
    return _metrics(rows)


def learning_gate(user_id, symbol, setup=None, session=None, regime=None):
    key=(str(user_id),str(symbol).upper(),setup,session,regime)
    cached=_GATE_CACHE.get(key)
    now=time.monotonic()
    if cached and now-cached[0] < _GATE_CACHE_TTL:
        return dict(cached[1])
    m=performance_snapshot(user_id,symbol,setup,session,regime,50)
    if m["trades"] < 20:
        result={"status":"LEARNING","approved":True,"modifier":1.0,"reason":"Live sample is still below 20 completed trades","metrics":m}
        _GATE_CACHE[key]=(now,result); return result
    if m["expectancy_r"] <= 0 or (m["profit_factor"] is not None and m["profit_factor"] < 1.0):
        result={"status":"DEMOTE","approved":False,"modifier":0.35,"reason":"Recent live performance is negative; setup is heavily reduced","metrics":m}
        _GATE_CACHE[key]=(now,result); return result
    if m["expectancy_r"] < 0.05 or (m["profit_factor"] is not None and m["profit_factor"] < 1.05):
        result={"status":"CAUTION","approved":True,"modifier":0.60,"reason":"Recent live edge is weak; setup stays at reduced risk","metrics":m}
        _GATE_CACHE[key]=(now,result); return result
    if m["expectancy_r"] >= 0.15 and (m["profit_factor"] is None or m["profit_factor"] >= 1.30):
        result={"status":"PROMOTE","approved":True,"modifier":1.0,"reason":"Recent live performance supports the setup","metrics":m}
        _GATE_CACHE[key]=(now,result); return result
    result={"status":"STABLE","approved":True,"modifier":0.80,"reason":"Recent live performance is positive but not strong enough for promotion","metrics":m}
    _GATE_CACHE[key]=(now,result); return result
