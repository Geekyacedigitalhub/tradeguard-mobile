from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

@dataclass
class Position:
    id: int
    symbol: str
    side: str
    quantity: float
    entry: float
    current_price: float
    stop_loss: float
    take_profit: float
    status: str = "open"
    opened_at: str = ""
    closed_at: Optional[str] = None
    close_reason: Optional[str] = None
    realized_pnl: float = 0.0

    def __post_init__(self):
        if not self.opened_at:
            self.opened_at = datetime.now(timezone.utc).isoformat()

positions: dict[int, Position] = {}
_next_id = 1

def open_paper_position(signal: dict, quantity: float) -> Position:
    global _next_id
    if signal["signal"] not in ("BUY", "SELL"):
        raise ValueError("Only BUY or SELL signals can open a position")
    position = Position(
        id=_next_id,
        symbol=signal["symbol"],
        side=signal["signal"],
        quantity=quantity,
        entry=float(signal["entry"]),
        current_price=float(signal["entry"]),
        stop_loss=float(signal["stop_loss"]),
        take_profit=float(signal["take_profit"]),
    )
    positions[position.id] = position
    _next_id += 1
    return position

def update_position(position: Position, price: float) -> Position:
    position.current_price = price
    if position.side == "BUY":
        position.realized_pnl = (price - position.entry) * position.quantity
        if price <= position.stop_loss:
            close_position(position, "stop_loss")
        elif price >= position.take_profit:
            close_position(position, "take_profit")
    else:
        position.realized_pnl = (position.entry - price) * position.quantity
        if price >= position.stop_loss:
            close_position(position, "stop_loss")
        elif price <= position.take_profit:
            close_position(position, "take_profit")
    return position

def close_position(position: Position, reason: str = "manual") -> Position:
    position.status = "closed"
    position.close_reason = reason
    position.closed_at = datetime.now(timezone.utc).isoformat()
    return position

def list_positions(status: Optional[str] = None):
    values=list(positions.values())
    return [p for p in values if not status or p.status == status]
