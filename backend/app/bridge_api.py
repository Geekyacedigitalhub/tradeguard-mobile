import os
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from .db import connection

router=APIRouter(prefix="/v1/bridge",tags=["mt5-bridge"])

BRIDGE_SECRET=os.getenv("MT5_BRIDGE_SECRET")

def require_bridge(secret):
    if not BRIDGE_SECRET or not secret or secret != BRIDGE_SECRET:
        raise HTTPException(401,"Invalid bridge credentials")

class Heartbeat(BaseModel):
    account: str | None = None
    environment: str = "demo"
    terminal: str = "MT5"

class CommandResult(BaseModel):
    command_id: int
    status: str
    result: dict = {}

@router.post("/heartbeat")
def heartbeat(body:Heartbeat,x_bridge_secret:str|None=Header(default=None)):
    require_bridge(x_bridge_secret)
    return {"ok":True,"connected":True,"provider":"MT5","environment":body.environment,"account":body.account,"terminal":body.terminal}

@router.get("/commands")
def commands(x_bridge_secret:str|None=Header(default=None),limit:int=10):
    require_bridge(x_bridge_secret)
    limit=max(1,min(limit,50))
    with connection() as conn:
        rows=conn.execute(
            """SELECT id,user_id,command_type,payload,created_at
               FROM bridge_commands
               WHERE status='pending'
               ORDER BY id
               LIMIT %s""",(limit,)
        ).fetchall()
        ids=[r[0] for r in rows]
        if ids:
            conn.execute("UPDATE bridge_commands SET status='claimed',claimed_at=now() WHERE id = ANY(%s)",(ids,))
    return {"commands":[{"id":r[0],"user_id":str(r[1]),"type":r[2],"payload":r[3],"created_at":r[4]} for r in rows]}

@router.post("/commands/result")
def command_result(body:CommandResult,x_bridge_secret:str|None=Header(default=None)):
    require_bridge(x_bridge_secret)
    if body.status not in ("completed","failed"):
        raise HTTPException(400,"Status must be completed or failed")
    with connection() as conn:
        updated=conn.execute(
            "UPDATE bridge_commands SET status=%s,completed_at=now(),result=%s::jsonb WHERE id=%s AND status='claimed' RETURNING id",
            (body.status,__import__("json").dumps(body.result),body.command_id)
        ).fetchone()
    if not updated:
        raise HTTPException(404,"Bridge command not found or already completed")
    return {"ok":True,"command_id":body.command_id,"status":body.status}
