import json
from .db import connection

def latest_validation_gate(user_id:str,symbol:str)->dict:
    """Return whether a previously saved MTF validation sample supports automation."""
    try:
        with connection() as conn:
            row=conn.execute("""SELECT report FROM strategy_reviews
                WHERE user_id=%s AND symbol=%s AND timeframe='MTF'
                ORDER BY created_at DESC LIMIT 1""",(user_id,symbol.upper())).fetchone()
    except Exception:
        return {"approved":False,"reason":"No stored validation"}
    if not row:
        return {"approved":False,"reason":"No stored validation"}
    report=row[0] or {}
    trades=int(report.get("trades") or 0)
    expectancy=float(report.get("expectancy_r") or 0)
    pf=report.get("profit_factor")
    if report.get("status")!="ok":
        return {"approved":False,"reason":"Stored validation did not complete"}
    if trades<30:
        return {"approved":False,"reason":"Historical sample is below 30 trades"}
    if expectancy<=0:
        return {"approved":False,"reason":"Historical expectancy is non-positive"}
    if pf is not None and float(pf)<1:
        return {"approved":False,"reason":"Historical profit factor is below 1"}
    return {"approved":True,"reason":"Stored MTF validation sample passes the historical evidence gate","trades":trades,"expectancy_r":expectancy,"profit_factor":pf}
