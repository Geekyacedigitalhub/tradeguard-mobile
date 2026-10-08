import os
import secrets
from urllib.parse import urlencode
import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from .auth import current_user
from .db import connection

router = APIRouter(prefix="/v1/ctrader", tags=["ctrader"])
CTRADER_CLIENT_ID = os.getenv("CTRADER_CLIENT_ID")
CTRADER_CLIENT_SECRET = os.getenv("CTRADER_CLIENT_SECRET")
CTRADER_REDIRECT_URI = os.getenv("CTRADER_REDIRECT_URI", "https://tradeguard-api.fastapicloud.dev/v1/ctrader/callback")
CTRADER_SCOPE = os.getenv("CTRADER_SCOPE", "trading")
CTRADER_AUTH_URL = "https://id.ctrader.com/my/settings/openapi/grantingaccess/"
CTRADER_TOKEN_URL = "https://openapi.ctrader.com/apps/token"

def _cipher():
    secret = os.getenv("JWT_SECRET")
    if not secret:
        raise RuntimeError("JWT_SECRET environment variable is required")
    import base64, hashlib
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))

def _encrypt(value):
    return _cipher().encrypt(value.encode()).decode()

def _require_config():
    if not CTRADER_CLIENT_ID or not CTRADER_CLIENT_SECRET:
        raise HTTPException(503, "cTrader Open API is not configured on the server")

@router.get("/connect")
def connect(user=Depends(current_user)):
    _require_config()
    state = secrets.token_urlsafe(32)
    with connection() as conn:
        conn.execute("INSERT INTO ctrader_oauth_states (state,user_id,expires_at) VALUES (%s,%s,now() + interval '10 minutes')", (state, user["id"]))
    query = urlencode({"client_id": CTRADER_CLIENT_ID, "redirect_uri": CTRADER_REDIRECT_URI, "scope": CTRADER_SCOPE, "product": "web", "state": state})
    return {"authorization_url": f"{CTRADER_AUTH_URL}?{query}", "redirect_uri": CTRADER_REDIRECT_URI}

@router.get("/callback", response_class=HTMLResponse)
async def callback(code: str | None = Query(default=None), state: str | None = Query(default=None), error: str | None = Query(default=None)):
    if error:
        return HTMLResponse(f"<html><body><h2>TradeGuard cTrader connection cancelled</h2><p>{error}</p><script>window.close()</script></body></html>", status_code=400)
    _require_config()
    if not code or not state:
        raise HTTPException(400, "Missing cTrader authorization code or state")
    with connection() as conn:
        row = conn.execute("DELETE FROM ctrader_oauth_states WHERE state=%s AND expires_at > now() RETURNING user_id", (state,)).fetchone()
    if not row:
        raise HTTPException(400, "Invalid or expired cTrader OAuth state")
    user_id = str(row[0])
    params = {"grant_type":"authorization_code","code":code,"redirect_uri":CTRADER_REDIRECT_URI,"client_id":CTRADER_CLIENT_ID,"client_secret":CTRADER_CLIENT_SECRET}
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(CTRADER_TOKEN_URL, params=params, headers={"Accept":"application/json"})
    data = response.json()
    if response.status_code >= 400 or data.get("errorCode"):
        raise HTTPException(502, data.get("description") or data.get("errorCode") or "cTrader token exchange failed")
    access_token, refresh_token = data.get("accessToken"), data.get("refreshToken")
    expires_in = int(data.get("expiresIn") or 0)
    if not access_token or not refresh_token:
        raise HTTPException(502, "cTrader returned an incomplete OAuth token")
    with connection() as conn:
        conn.execute("""INSERT INTO ctrader_accounts (user_id,access_token,refresh_token,expires_at,status,updated_at)
            VALUES (%s,%s,%s,now() + (%s * interval '1 second'),'authorized',now())
            ON CONFLICT (user_id) DO UPDATE SET access_token=EXCLUDED.access_token,refresh_token=EXCLUDED.refresh_token,
            expires_at=EXCLUDED.expires_at,status='authorized',updated_at=now()""",
            (user_id, _encrypt(access_token), _encrypt(refresh_token), expires_in))
    return HTMLResponse("<html><body><h2>TradeGuard cTrader connected</h2><p>Your cTrader authorization was received. Return to TradeGuard.</p><script>window.close()</script></body></html>")

@router.get("/status")
def status(user=Depends(current_user)):
    with connection() as conn:
        row = conn.execute("SELECT status,ctid_trader_account_id,is_live,expires_at,updated_at FROM ctrader_accounts WHERE user_id=%s", (user["id"],)).fetchone()
    if not row:
        return {"connected":False,"provider":"cTrader"}
    return {"connected":row[0]=="authorized","provider":"cTrader","account_id":str(row[1]) if row[1] else None,"is_live":bool(row[2]) if row[2] is not None else None,"expires_at":row[3],"updated_at":row[4]}
