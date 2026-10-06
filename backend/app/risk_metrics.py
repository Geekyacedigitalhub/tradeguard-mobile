from .db import connection
import time

_LOSS_STREAK_CACHE={}
_LOSS_STREAK_CACHE_TTL=5

def invalidate_loss_streak(user_id):
    _LOSS_STREAK_CACHE.pop(str(user_id),None)

def consecutive_losses(user_id:str)->int:
    key=str(user_id)
    cached=_LOSS_STREAK_CACHE.get(key)
    now=time.monotonic()
    if cached and now-cached[0] < _LOSS_STREAK_CACHE_TTL:
        return cached[1]
    with connection() as conn:
        rows=conn.execute("""SELECT realized_pnl FROM positions
            WHERE user_id=%s AND status='closed'
            ORDER BY closed_at DESC LIMIT 20""",(user_id,)).fetchall()
    streak=0
    for (pnl,) in rows:
        if float(pnl or 0)<0: streak+=1
        else: break
    _LOSS_STREAK_CACHE[key]=(now,streak)
    return streak
