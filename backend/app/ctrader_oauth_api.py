import os
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
import httpx
from fastapi import APIRouter, Depends, HTTPException
from .auth import current_user
from .db import connection

router=APIRouter(prefix="/v1/ctrader",tags=["ctrader"])
CLIENT_ID=os.getenv("CTRADER_CLIENT_ID","").strip()
CLIENT_SECRET=os.getenv("CTRADER_CLIENT_SECRET","").strip()
REDIRECT_URI=os.getenv("CTRADER_REDIRECT_URI","https://tradeguard-api.fastapicloud.dev/v1/ctrader/oauth/callback").strip()

def _require_config():
    if not CLIENT_ID or not CLIENT_SECRET:
        raise HTTPException(503,"cTrader Open API credentials are not configured")

@router.get("/oauth/start")
def oauth_start(user=Depends(current_user)):
    _require_config()
    state=f"{user['id']}:{os.urandom(18).hex()}"
    with connection() as conn:
        conn.execute(
            "INSERT INTO audit_events (user_id,event_type,payload) VALUES (%s,'ctrader_oauth_state',%s::jsonb)",
            (user["id"],__import__("json").dumps({"state":state,"expires_at":(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat()})),
        )
    query=urlencode({"client_id":CLIENT_ID,"redirect_uri":REDIRECT_URI,"scope":"trading","product":"web","state":state})
    return {"authorization_url":f"https://id.ctrader.com/my/settings/openapi/grantingaccess/?{query}"}

@router.get("/oauth/callback")
def oauth_callback(code:str,state:str):
    if ":" not in state:
        raise HTTPException(400,"Invalid OAuth state")
    user_id=state.split(":",1)[0]
    import json
    with connection() as conn:
        row=conn.execute(
            """SELECT payload,created_at FROM audit_events
               WHERE user_id=%s AND event_type='ctrader_oauth_state'
               ORDER BY created_at DESC LIMIT 1""",(user_id,)
        ).fetchone()
    if not row or (row[0] or {}).get("state")!=state:
        raise HTTPException(400,"OAuth state is invalid or expired")
    if datetime.now(timezone.utc)-row[1] > timedelta(minutes=10):
        raise HTTPException(400,"OAuth state expired")
    _require_config()
    response=httpx.get(
        "https://openapi.ctrader.com/apps/token",
        params={"grant_type":"authorization_code","code":code,"redirect_uri":REDIRECT_URI,"client_id":CLIENT_ID,"client_secret":CLIENT_SECRET},
        timeout=15,
    )
    response.raise_for_status()
    token=response.json()
    if token.get("errorCode"):
        raise HTTPException(400,token.get("description") or token["errorCode"])
    expires=datetime.now(timezone.utc)+timedelta(seconds=int(token.get("expiresIn",2628000)))
    with connection() as conn:
        conn.execute(
            """INSERT INTO ctrader_connections
               (user_id,access_token,refresh_token,expires_at,updated_at)
               VALUES (%s,%s,%s,%s,now())
               ON CONFLICT (user_id) DO UPDATE
               SET access_token=EXCLUDED.access_token,
                   refresh_token=EXCLUDED.refresh_token,
                   expires_at=EXCLUDED.expires_at,
                   updated_at=now()""",
            (user_id,token.get("accessToken"),token.get("refreshToken"),expires),
        )
    return {"connected":True,"message":"cTrader authorization completed. You can close this page and return to TradeGuard."}

@router.get("/oauth/status")
def oauth_status(user=Depends(current_user)):
    with connection() as conn:
        row=conn.execute(
            "SELECT account_id,environment,expires_at,updated_at FROM ctrader_connections WHERE user_id=%s",
            (user["id"],)
        ).fetchone()
    if not row:
        return {"authorized":False}
    return {"authorized":True,"account_id":row[0],"environment":row[1],"expires_at":row[2],"updated_at":row[3]}
