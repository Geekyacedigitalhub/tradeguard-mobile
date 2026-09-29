from fastapi import APIRouter, HTTPException
from .trade_manager import list_positions, close_position

router = APIRouter(prefix="/v1/trades", tags=["trades"])

@router.get("")
def trades(status: str | None = None):
    return {"trades": [p.__dict__ for p in list_positions(status)]}

@router.post("/{position_id}/close")
def close_trade(position_id: int):
    matches=[p for p in list_positions() if p.id == position_id]
    if not matches:
        raise HTTPException(404, "Position not found")
    return close_position(matches[0]).__dict__

@router.post("/close-all")
def close_all():
    closed=[]
    for p in list_positions("open"):
        closed.append(close_position(p).__dict__)
    return {"trades": closed}
