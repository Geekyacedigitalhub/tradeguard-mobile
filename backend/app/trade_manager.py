from dataclasses import dataclass
from typing import Optional
from .db import connection

@dataclass
class Position:
    id:int
    user_id:str
    symbol:str
    side:str
    quantity:float
    entry:float
    current_price:float
    stop_loss:float
    take_profit:float
    status:str="open"
    opened_at:str=""
    closed_at:Optional[str]=None
    close_reason:Optional[str]=None
    realized_pnl:float=0.0

def _from_row(row):
    return Position(int(row[0]),str(row[1]),row[2],row[3],float(row[4]),float(row[5]),float(row[6]),float(row[7]),float(row[8]),row[9],row[10].isoformat() if row[10] else "",row[11].isoformat() if row[11] else None,row[12],float(row[13] or 0))

def open_paper_position(user_id, signal, quantity):
    if signal.get("signal") not in ("BUY","SELL"): raise ValueError("Only BUY or SELL signals can open a position")
    with connection() as conn:
        row=conn.execute("""INSERT INTO positions (user_id,symbol,side,quantity,entry,current_price,stop_loss,take_profit,status)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'open')
        RETURNING id,user_id,symbol,side,quantity,entry,current_price,stop_loss,take_profit,status,opened_at,closed_at,close_reason,realized_pnl""",
        (user_id,signal["symbol"],signal["signal"],quantity,float(signal["entry"]),float(signal["entry"]),float(signal["stop_loss"]),float(signal["take_profit"]))).fetchone()
    return _from_row(row)

def list_positions(status=None, user_id=None):
    where=[]; args=[]
    if status: where.append("status=%s"); args.append(status)
    if user_id: where.append("user_id=%s"); args.append(user_id)
    clause=(" WHERE "+" AND ".join(where)) if where else ""
    with connection() as conn:
        rows=conn.execute("SELECT id,user_id,symbol,side,quantity,entry,current_price,stop_loss,take_profit,status,opened_at,closed_at,close_reason,realized_pnl FROM positions"+clause+" ORDER BY opened_at DESC",tuple(args)).fetchall()
    return [_from_row(row) for row in rows]

def close_position(p, reason="manual", current_price=None):
    price=float(current_price if current_price is not None else p.current_price)
    pnl=(price-p.entry)*p.quantity if p.side=="BUY" else (p.entry-price)*p.quantity
    with connection() as conn:
        row=conn.execute("""UPDATE positions SET status='closed',current_price=%s,realized_pnl=%s,closed_at=now(),close_reason=%s
        WHERE id=%s AND user_id=%s AND status='open'
        RETURNING id,user_id,symbol,side,quantity,entry,current_price,stop_loss,take_profit,status,opened_at,closed_at,close_reason,realized_pnl""",
        (price,pnl,reason,p.id,p.user_id)).fetchone()
    return _from_row(row) if row else p

def mark_prices(prices):
    for p in list_positions("open"):
        symbol=p.symbol.replace("/USD","USDT")
        if symbol not in prices: continue
        price=float(prices[symbol])
        hit=None
        if p.side=="BUY":
            if price<=p.stop_loss: hit="stop_loss"
            elif price>=p.take_profit: hit="take_profit"
        else:
            if price>=p.stop_loss: hit="stop_loss"
            elif price<=p.take_profit: hit="take_profit"
        if hit:
            close_position(p,hit,price)
        else:
            pnl=(price-p.entry)*p.quantity if p.side=="BUY" else (p.entry-price)*p.quantity
            with connection() as conn:
                conn.execute("UPDATE positions SET current_price=%s,realized_pnl=%s WHERE id=%s AND status='open'",(price,pnl,p.id))
