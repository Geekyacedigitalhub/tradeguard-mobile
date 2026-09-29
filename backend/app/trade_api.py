from fastapi import APIRouter, Depends, HTTPException
from .auth import current_user
from .trade_manager import list_positions, close_position

router = APIRouter(prefix="/v1/trades", tags=["trades"])

def serialize(p):
    return {k:v for k,v in p.__dict__.items() if k != "user_id"}

@router.get("")
def trades(status: str | None = None, user=Depends(current_user)):
    return {"trades":[serialize(p) for p in list_positions(status,user["id"])]}

@router.post("/{position_id}/close")
def close_trade(position_id: int, user=Depends(current_user)):
    matches=[p for p in list_positions(user_id=user["id"]) if p.id == position_id]
    if not matches: raise HTTPException(404,"Position not found")
    return serialize(close_position(matches[0]))

@router.post("/close-all")
def close_all(user=Depends(current_user)):
    closed=[]
    for p in list_positions("open",user["id"]): closed.append(serialize(close_position(p)))
    return {"trades":closed}
