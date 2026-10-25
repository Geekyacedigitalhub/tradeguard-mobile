import time
from .db import connection

_VALIDATION_GATE_CACHE={}
_VALIDATION_GATE_CACHE_TTL=300

def latest_validation_gate(user_id:str,symbol:str)->dict:
    """Return whether a previously saved MTF validation sample supports automation."""
    key=(str(user_id),str(symbol).upper())
    cached=_VALIDATION_GATE_CACHE.get(key)
    now=time.monotonic()
    if cached and now-cached[0] < _VALIDATION_GATE_CACHE_TTL:
        return dict(cached[1])
    try:
        with connection() as conn:
            row=conn.execute("""SELECT report FROM strategy_reviews
                WHERE user_id=%s AND symbol=%s AND timeframe='MTF'
                ORDER BY created_at DESC LIMIT 1""",(user_id,symbol.upper())).fetchone()
    except Exception:
        result={"approved":False,"reason":"No stored validation"}
        _VALIDATION_GATE_CACHE[key]=(now,result)
        return dict(result)
    if not row:
        result={"approved":False,"reason":"No stored validation"}
    else:
        report=row[0] or {}
        trades=int(report.get("trades") or 0)
        expectancy=float(report.get("expectancy_r") or 0)
        pf=report.get("profit_factor")
        if report.get("status")!="ok":
            result={"approved":False,"reason":"Stored validation did not complete"}
        elif trades<30:
            result={"approved":False,"reason":"Historical sample is below 30 trades"}
        elif expectancy<=0:
            result={"approved":False,"reason":"Historical expectancy is non-positive"}
        elif pf is not None and float(pf)<1:
            result={"approved":False,"reason":"Historical profit factor is below 1"}
        else:
            result={"approved":True,"reason":"Stored MTF validation sample passes the historical evidence gate","trades":trades,"expectancy_r":expectancy,"profit_factor":pf}
    _VALIDATION_GATE_CACHE[key]=(now,result)
    return dict(result)
