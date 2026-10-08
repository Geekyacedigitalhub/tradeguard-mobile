from .learning import performance_snapshot, _metrics
from .db import connection

def optimizer_gate(user_id, symbol, setup=None, session=None, regime=None):
    exact = performance_snapshot(user_id, symbol, setup, session, regime, 50)
    base = exact if exact["trades"] >= 10 else performance_snapshot(user_id, symbol, None, None, None, 50)
    weight = min(1.0, base["trades"] / 30.0)
    adjusted = base["expectancy_r"] * weight
    if base["trades"] < 10:
        return {"status":"INSUFFICIENT","approved":True,"modifier":1.0,"reason":"Not enough live evidence to optimize this slice","metrics":base}
    if adjusted <= 0:
        return {"status":"DEMOTE","approved":False,"modifier":0.35,"reason":"Measured live expectancy is negative for this opportunity slice","metrics":base}
    if adjusted < 0.05:
        return {"status":"CAUTION","approved":True,"modifier":0.60,"reason":"Measured live edge is weak after sample adjustment","metrics":base}
    if adjusted >= 0.15 and (base["profit_factor"] is None or base["profit_factor"] >= 1.30):
        return {"status":"PROMOTE","approved":True,"modifier":1.0,"reason":"Measured live edge is strong enough to promote this slice","metrics":base}
    return {"status":"STABLE","approved":True,"modifier":0.80,"reason":"Measured live edge is positive but not yet strong enough for promotion","metrics":base}

def optimizer_snapshot(user_id, limit=100):
    with connection() as conn:
        rows = conn.execute(
            """SELECT COALESCE(symbol,'UNKNOWN'),
                      COALESCE(context->>'session','UNKNOWN'),
                      COALESCE(context->>'regime','UNKNOWN'),
                      COALESCE(context->>'setup',setup,'UNKNOWN'),
                      r_multiple
                 FROM trade_journal
                WHERE user_id=%s AND r_multiple IS NOT NULL AND closed_at IS NOT NULL
                ORDER BY closed_at DESC LIMIT %s""",
            (user_id, max(1, min(int(limit), 200)))
        ).fetchall()

    groups = {}
    for symbol, session, regime, setup, r in rows:
        groups.setdefault((str(symbol), str(session), str(regime), str(setup)), []).append(float(r or 0))

    ranked = []
    for (symbol, session, regime, setup), rs in groups.items():
        metrics = _metrics([(r,) for r in rs])
        weight = min(1.0, metrics["trades"] / 30.0)
        adjusted = metrics["expectancy_r"] * weight
        if metrics["trades"] < 10:
            status = "INSUFFICIENT"
        elif adjusted <= 0:
            status = "DEMOTE"
        elif adjusted < 0.05:
            status = "CAUTION"
        elif adjusted >= 0.15 and (metrics["profit_factor"] is None or metrics["profit_factor"] >= 1.30):
            status = "PROMOTE"
        else:
            status = "STABLE"
        ranked.append({
            "symbol": symbol,
            "session": session,
            "regime": regime,
            "setup": setup,
            "status": status,
            "adjusted_expectancy_r": round(adjusted, 4),
            "sample_weight": round(weight, 3),
            "metrics": metrics,
        })

    ranked.sort(
        key=lambda x: (
            x["status"] == "PROMOTE",
            x["adjusted_expectancy_r"],
            x["metrics"]["profit_factor"] or 0,
        ),
        reverse=True,
    )
    return ranked
