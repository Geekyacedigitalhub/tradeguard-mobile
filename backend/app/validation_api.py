from fastapi import APIRouter, Depends, HTTPException
from .auth import current_user
from .db import connection
from .market_data import candles_for
from .strategy import backtest_multi_timeframe
from .intelligence import validation_summary, market_intelligence

router=APIRouter(prefix="/v1/strategy",tags=["strategy"])

@router.get("/validate")
async def validate_strategy(
    symbol:str="EURUSD",
    limit_5m:int=1200,
    cost_r:float=0.0,
    user=Depends(current_user),
):
    symbol=symbol.upper().strip()
    cost_r=max(0.0,min(float(cost_r),0.5))
    limit_5m=max(500,min(int(limit_5m),2400))
    try:
        c1,c15,c5=await __import__("asyncio").gather(
            candles_for(symbol,"1h",260,user["id"]),
            candles_for(symbol,"15m",600,user["id"]),
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
            conn.execute("""CREATE TABLE IF NOT EXISTS strategy_reviews(
                id BIGSERIAL PRIMARY KEY,user_id TEXT NOT NULL,symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,report JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""")
            conn.execute("""INSERT INTO strategy_reviews(user_id,symbol,timeframe,report)
                VALUES (%s,%s,'MTF',%s::jsonb)""",(user["id"],symbol,__import__("json").dumps(result)))
        return result
    except Exception as exc:
        raise HTTPException(503,f"MTF validation data unavailable: {exc}")

@router.get("/reviews")
def strategy_reviews(limit:int=20,user=Depends(current_user)):
    limit=max(1,min(int(limit),100))
    with connection() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS strategy_reviews(
            id BIGSERIAL PRIMARY KEY,user_id TEXT NOT NULL,symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,report JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""")
        rows=conn.execute("""SELECT id,symbol,timeframe,report,created_at
            FROM strategy_reviews WHERE user_id=%s ORDER BY created_at DESC LIMIT %s""",(user["id"],limit)).fetchall()
    return {"reviews":[{"id":r[0],"symbol":r[1],"timeframe":r[2],"report":r[3],"created_at":r[4]} for r in rows]}


@router.get("/live")
async def live_strategy(symbol:str="EURUSD",user=Depends(current_user)):
    symbol=symbol.upper().strip()
    try:
        import asyncio
        c1,c15,c5=await asyncio.gather(
            candles_for(symbol,"1h",220,user["id"]),
            candles_for(symbol,"15m",220,user["id"]),
            candles_for(symbol,"5m",220,user["id"]),
        )
        from .strategy import analyze_multi_timeframe
        signal=analyze_multi_timeframe(c1,c15,c5)
        return {"symbol":symbol,"signal":signal,"intelligence":market_intelligence(signal,c5)}
    except Exception as exc:
        raise HTTPException(503,f"Live strategy data unavailable: {exc}")
