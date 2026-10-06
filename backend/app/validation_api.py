from fastapi import APIRouter, Depends, HTTPException
from .auth import current_user
from .db import connection
from .market_data import candles_for
from .strategy import backtest_multi_timeframe
from .intelligence import validation_summary, market_intelligence
from .technical_engine import deep_market_analysis

router=APIRouter(prefix="/v1/strategy",tags=["strategy"])

# Validation is intentionally expensive with the larger MTF history. Cache the
# latest result briefly so opening the Strategy screen repeatedly does not
# replay thousands of candles each time.
_validation_cache={}
VALIDATION_CACHE_TTL=300

@router.get("/validate")
async def validate_strategy(
    symbol:str="EURUSD",
    limit_5m:int=5000,
    cost_r:float=0.0,
    user=Depends(current_user),
):
    symbol=symbol.upper().strip()
    cost_r=max(0.0,min(float(cost_r),0.5))
    limit_5m=max(500,min(int(limit_5m),5000))
    cache_key=(str(user["id"]),symbol,cost_r,limit_5m)
    now=__import__("time").monotonic()
    cached=_validation_cache.get(cache_key)
    if cached and now-cached["time"] < VALIDATION_CACHE_TTL:
        return cached["result"]

    try:
        c1,c15,c5=await __import__("asyncio").gather(
            candles_for(symbol,"1h",800,user["id"]),
            candles_for(symbol,"15m",2500,user["id"]),
            candles_for(symbol,"5m",limit_5m,user["id"]),
        )
        # Exclude the currently forming candle from the decision stream.
        if len(c5)>1 and c5[-1].time is not None:
            c5=c5[:-1]
        report=backtest_multi_timeframe(c1,c15,c5,horizon=24,cost_r=cost_r)
        result={
            "symbol":symbol,
            "engine":"TradeGuard MTF walk-forward v2",
            "lookahead_safe":True,
            "execution":False,
            "cost_r":cost_r,
            "history":{"1h":len(c1),"15m":len(c15),"5m":len(c5)},
            **report,
            "assessment":validation_summary(report),
        }
        with connection() as conn:
            conn.execute("""INSERT INTO strategy_reviews(user_id,symbol,timeframe,report)
                VALUES (%s,%s,'MTF',%s::jsonb)""",(user["id"],symbol,__import__("json").dumps(result)))
        _validation_cache[cache_key]={"time":now,"result":result}
        from .validation_gate import _VALIDATION_GATE_CACHE
        _VALIDATION_GATE_CACHE.pop((str(user["id"]),symbol),None)
        return result
    except Exception as exc:
        raise HTTPException(503,f"MTF validation data unavailable: {exc}")

@router.get("/reviews")
def strategy_reviews(limit:int=20,user=Depends(current_user)):
    limit=max(1,min(int(limit),100))
    with connection() as conn:
        rows=conn.execute("""SELECT id,symbol,timeframe,report,created_at
            FROM strategy_reviews WHERE user_id=%s ORDER BY created_at DESC LIMIT %s""",(user["id"],limit)).fetchall()
    return {"reviews":[{"id":r[0],"symbol":r[1],"timeframe":r[2],"report":r[3],"created_at":r[4]} for r in rows]}


@router.get("/live")
async def live_strategy(symbol:str="EURUSD",user=Depends(current_user)):
    symbol=symbol.upper().strip()
    try:
        # Reuse the shared MTF analysis path used by the scanner/workers so a
        # live strategy request does not trigger a second candle download and
        # duplicate deep-analysis work for the same user/symbol.
        from .main import multi_timeframe_analysis
        result=await multi_timeframe_analysis(symbol,str(user["id"]))
        return {
            "symbol":symbol,
            "signal":result,
            "intelligence":result.get("intelligence"),
            "deep_analysis":result.get("deep_analysis"),
        }
    except Exception as exc:
        raise HTTPException(503,f"Live strategy data unavailable: {exc}")
