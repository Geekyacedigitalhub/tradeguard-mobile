from dataclasses import dataclass
from typing import Optional
from .db import connection
from .notifications_api import notification_event, send_push
from .journal_api import record_closed_trade

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
    if row:
        closed=_from_row(row)
        risk=abs(float(p.entry)-float(p.stop_loss))
        r_multiple=(float(closed.realized_pnl)/(risk*float(p.quantity))) if risk>0 and float(p.quantity)>0 else 0.0
        try: record_closed_trade(closed,r_multiple)
        except Exception: pass
        return closed
    return p

def _refresh_accounts():
    with connection() as conn:
        users=conn.execute("SELECT user_id,balance FROM account_state").fetchall()
        if not users:
            return
        positions=conn.execute("SELECT user_id,realized_pnl FROM positions WHERE status='open'").fetchall()
        unrealized={}
        for user_id,pnl in positions:
            unrealized[user_id]=unrealized.get(user_id,0.0)+float(pnl or 0)
        for user_id,balance in users:
            open_pnl=unrealized.get(user_id,0.0)
            equity=float(balance)+open_pnl
            drawdown=max(0.0,(float(balance)-equity)/max(float(balance),1)*100)
            conn.execute("UPDATE account_state SET equity=%s,drawdown=%s,today_pl=%s,updated_at=now() WHERE user_id=%s",(equity,drawdown,open_pnl,user_id))

def mark_prices(prices,open_positions=None):
    updates=[]
    positions=open_positions if open_positions is not None else list_positions("open")
    for p in positions:
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
            closed=close_position(p,hit,price)
            notification_event(p.user_id,"notification_trade_closed",{"symbol":p.symbol,"side":p.side,"reason":hit,"entry":p.entry,"exit":price,"pnl":closed.realized_pnl})
            label="Take profit" if hit=="take_profit" else "Stop loss"
            send_push(p.user_id,f"{label} hit · {p.symbol}",f"Position closed at {price}. P/L: {closed.realized_pnl:.2f}",{"type":"trade_closed","symbol":p.symbol,"reason":hit,"pnl":closed.realized_pnl})
        else:
            pnl=(price-p.entry)*p.quantity if p.side=="BUY" else (p.entry-price)*p.quantity
            updates.append((price,pnl,p.id))
    if updates:
        with connection() as conn:
            for price,pnl,position_id in updates:
                conn.execute("UPDATE positions SET current_price=%s,realized_pnl=%s WHERE id=%s AND status='open'",(price,pnl,position_id))
    _refresh_accounts()
