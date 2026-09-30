import json
import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from .auth import current_user
from .db import connection

router=APIRouter(prefix="/v1/notifications",tags=["notifications"])

def notification_event(user_id,event_type,payload):
    with connection() as conn:
        conn.execute("INSERT INTO audit_events (user_id,event_type,payload) VALUES (%s,%s,%s::jsonb)",(user_id,event_type,json.dumps(payload)))

EXPO_PUSH_URL="https://exp.host/--/api/v2/push/send"

def send_push(user_id,title,body,data=None):
    with connection() as conn:
        row=conn.execute("SELECT payload->>'token' FROM audit_events WHERE user_id=%s AND event_type='push_token_registered' ORDER BY created_at DESC LIMIT 1",(user_id,)).fetchone()
    token=row[0] if row else None
    if not token:
        return False
    try:
        response=httpx.post(EXPO_PUSH_URL,json={"to":token,"title":title,"body":body,"sound":"default","data":data or {}},timeout=10)
        return response.is_success
    except Exception:
        return False

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
        rows=conn.execute("SELECT id,event_type,payload,created_at FROM audit_events WHERE user_id=%s AND event_type LIKE %s ORDER BY id DESC LIMIT 20",(user["id"],"notification_%")).fetchall()
    return {"events":[{"id":r[0],"type":r[1],"payload":r[2],"created_at":r[3]} for r in rows]}
