import json
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from .auth import current_user
from .db import connection

router=APIRouter(prefix="/v1/notifications",tags=["notifications"])

def notification_event(user_id,event_type,payload):
    with connection() as conn:
        conn.execute("INSERT INTO audit_events (user_id,event_type,payload) VALUES (%s,%s,%s::jsonb)",(user_id,event_type,json.dumps(payload)))

EXPO_PUSH_URL="https://exp.host/--/api/v2/push/send"

def _push_to_token(token,title,body,data=None):
    response=httpx.post(
        EXPO_PUSH_URL,
        json={
            "to":token,
            "title":title,
            "body":body,
            "sound":"default",
            "channelId":"tradeguard-alerts",
            "data":data or {},
        },
        timeout=10,
    )
    if not response.is_success:
        return {"ok":False,"status_code":response.status_code,"message":response.text[:500]}
    try:
        payload=response.json()
    except Exception:
        return {"ok":False,"status_code":response.status_code,"message":"Expo returned a non-JSON response"}
    item=(payload.get("data") or [{}])[0] if isinstance(payload,dict) else {}
    if item.get("status")=="ok":
        return {"ok":True,"status":"ok","id":item.get("id")}
    return {
        "ok":False,
        "status":item.get("status"),
        "error":item.get("details",{}).get("error") if isinstance(item.get("details"),dict) else None,
        "message":item.get("message") or "Expo rejected the push notification",
    }

def _latest_token(user_id):
    with connection() as conn:
        row=conn.execute(
            "SELECT payload->>'token',created_at FROM audit_events WHERE user_id=%s AND event_type='push_token_registered' ORDER BY created_at DESC LIMIT 1",
            (user_id,)
        ).fetchone()
    return row if row else (None,None)

def send_push(user_id,title,body,data=None):
    token,_=_latest_token(user_id)
    if not token:
        return False
    try:
        return bool(_push_to_token(token,title,body,data).get("ok"))
    except Exception:
        return False

class PushToken(BaseModel):
    token:str

@router.post("/token")
def save_token(body:PushToken,user=Depends(current_user)):
    if not body.token.startswith("ExponentPushToken["):
        return {"ok":False,"message":"Invalid Expo push token"}
    with connection() as conn:
        conn.execute(
            "INSERT INTO audit_events (user_id,event_type,payload) VALUES (%s,%s,%s::jsonb)",
            (user["id"],"push_token_registered",json.dumps({"token":body.token}))
        )
    return {"ok":True}

@router.get("/status")
def notification_status(user=Depends(current_user)):
    token,registered_at=_latest_token(user["id"])
    return {
        "registered":bool(token),
        "registered_at":registered_at,
        "provider":"expo",
    }

@router.post("/test")
def test_notification(user=Depends(current_user)):
    token,_=_latest_token(user["id"])
    if not token:
        raise HTTPException(409,"This phone has not registered an Expo push token yet. Open the latest TradeGuard app build and allow notifications first.")
    try:
        result=_push_to_token(
            token,
            "TradeGuard test alert",
            "Push notifications are connected and working.",
            {"type":"test_notification"},
        )
    except Exception as exc:
        result={"ok":False,"message":str(exc)[:500]}
    notification_event(user["id"],"notification_test",result)
    if not result.get("ok"):
        raise HTTPException(503,result.get("message") or result.get("error") or "Expo rejected the test notification")
    return {"ok":True,"message":"Test notification sent","provider":"expo","id":result.get("id")}

@router.get("/events")
def events(user=Depends(current_user)):
    with connection() as conn:
        rows=conn.execute(
            "SELECT id,event_type,payload,created_at FROM audit_events WHERE user_id=%s AND event_type LIKE %s ORDER BY id DESC LIMIT 20",
            (user["id"],"notification_%")
        ).fetchall()
    return {"events":[{"id":r[0],"type":r[1],"payload":r[2],"created_at":r[3]} for r in rows]}
