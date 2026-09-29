import json
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from .auth import current_user
from .db import connection

router=APIRouter(prefix="/v1/notifications",tags=["notifications"])

class PushToken(BaseModel):
    token:str

@router.post("/token")
def save_token(body:PushToken,user=Depends(current_user)):
    if not body.token.startswith("ExponentPushToken["):
        return {"ok":False,"message":"Invalid Expo push token"}
    with connection() as conn:
        conn.execute("INSERT INTO audit_events (user_id,event_type,payload) VALUES (%s,%s,%s::jsonb)",(user["id"],"push_token_registered",json.dumps({"token":body.token})))
    return {"ok":True}

@router.get("/events")
def events(user=Depends(current_user)):
    with connection() as conn:
        rows=conn.execute("SELECT id,event_type,payload,created_at FROM audit_events WHERE user_id=%s AND event_type LIKE 'notification_%' ORDER BY id DESC LIMIT 20",(user["id"],)).fetchall()
    return {"events":[{"id":r[0],"type":r[1],"payload":r[2],"created_at":r[3]} for r in rows]}
