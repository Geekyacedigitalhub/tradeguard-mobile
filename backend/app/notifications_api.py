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
        conn.execute(
            "INSERT INTO audit_events (user_id,event_type,payload) VALUES (%s,%s,%s::jsonb)",
            (user["id"],"push_token_registered",__import__("json").dumps({"token":body.token}))
        )
    return {"ok":True}
