from .db import connection

def consecutive_losses(user_id:str)->int:
    with connection() as conn:
        rows=conn.execute("""SELECT realized_pnl FROM positions
            WHERE user_id=%s AND status='closed'
            ORDER BY closed_at DESC LIMIT 20""",(user_id,)).fetchall()
    streak=0
    for (pnl,) in rows:
        if float(pnl or 0)<0: streak+=1
        else: break
    return streak
