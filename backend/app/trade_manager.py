from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

@dataclass
class Position:
    id:int; user_id:str; symbol:str; side:str; quantity:float; entry:float; current_price:float
    stop_loss:float; take_profit:float; status:str="open"; opened_at:str=""
    closed_at:Optional[str]=None; close_reason:Optional[str]=None; realized_pnl:float=0.0
    def __post_init__(self):
        if not self.opened_at: self.opened_at=datetime.now(timezone.utc).isoformat()

positions={}; _next_id=1

def open_paper_position(user_id, signal, quantity):
    global _next_id
    if signal.get("signal") not in ("BUY","SELL"): raise ValueError("Only BUY or SELL signals can open a position")
    p=Position(_next_id,user_id,signal["symbol"],signal["signal"],quantity,float(signal["entry"]),float(signal["entry"]),float(signal["stop_loss"]),float(signal["take_profit"]))
    positions[p.id]=p; _next_id+=1; return p

def update_position(p, price):
    p.current_price=price
    p.realized_pnl=(price-p.entry)*p.quantity if p.side=="BUY" else (p.entry-price)*p.quantity
    if p.side=="BUY":
        if price<=p.stop_loss: close_position(p,"stop_loss")
        elif price>=p.take_profit: close_position(p,"take_profit")
    else:
        if price>=p.stop_loss: close_position(p,"stop_loss")
        elif price<=p.take_profit: close_position(p,"take_profit")
    return p

def close_position(p, reason="manual"):
    p.status="closed"; p.close_reason=reason; p.closed_at=datetime.now(timezone.utc).isoformat(); return p

def list_positions(status=None, user_id=None):
    return [p for p in positions.values() if (not status or p.status==status) and (not user_id or p.user_id==user_id)]

def mark_prices(prices):
    for p in list_positions("open"):
        symbol=p.symbol.replace("/USD","USDT")
        if symbol in prices: update_position(p,float(prices[symbol]))
