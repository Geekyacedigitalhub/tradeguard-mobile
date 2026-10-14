import os
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
import httpx
from fastapi import APIRouter, Depends, HTTPException
from .auth import current_user
from .db import connection
from .ctrader_security import encrypt_token
from .ctrader_service import manager
from .ctrader_tokens import fresh_access_token
from .ctrader_snapshot_helpers import normalize_trade_side, scale_balance

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
    if not code.strip():
        raise HTTPException(400,"cTrader authorization code is missing")
    if not state.strip() or ":" not in state:
        raise HTTPException(400,"Invalid OAuth state")
    user_id=state.split(":",1)[0]
    # Consume the exact OAuth state atomically so the callback cannot be replayed.
    # Matching the state in SQL also avoids accepting a different, newer state for this user.
    with connection() as conn:
        row=conn.execute(
            """DELETE FROM audit_events
               WHERE user_id=%s AND event_type='ctrader_oauth_state'
                 AND payload->>'state'=%s
               RETURNING payload,created_at""",
            (user_id,state),
        ).fetchone()
    if not row:
        raise HTTPException(400,"OAuth state is invalid, expired, or already used")
    if datetime.now(timezone.utc)-row[1] > timedelta(minutes=10):
        raise HTTPException(400,"OAuth state expired")
    _require_config()
    try:
        response=httpx.get(
            "https://openapi.ctrader.com/apps/token",
            params={"grant_type":"authorization_code","code":code,"redirect_uri":REDIRECT_URI,"client_id":CLIENT_ID,"client_secret":CLIENT_SECRET},
            timeout=15,
        )
        response.raise_for_status()
        token=response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(502,"Unable to complete cTrader token exchange. Start authorization again.") from exc
    if not isinstance(token,dict):
        raise HTTPException(502,"cTrader returned an invalid token response")
    if token.get("errorCode"):
        raise HTTPException(400,token.get("description") or token["errorCode"])
    if not token.get("accessToken") or not token.get("refreshToken"):
        raise HTTPException(502,"cTrader token response is missing required credentials")
    try:
        expires=datetime.now(timezone.utc)+timedelta(seconds=int(token.get("expiresIn",2628000)))
    except (TypeError,ValueError,OverflowError) as exc:
        raise HTTPException(502,"cTrader returned an invalid token expiry") from exc
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
            (user_id,encrypt_token(token.get("accessToken")),encrypt_token(token.get("refreshToken")),expires),
        )
    return {"connected":True,"message":"cTrader authorization completed. You can close this page and return to TradeGuard."}

@router.get("/accounts")
async def accounts(user=Depends(current_user)):
    with connection() as conn:
        row=conn.execute(
            "SELECT access_token,environment FROM ctrader_connections WHERE user_id=%s",
            (user["id"],)
        ).fetchone()
    if not row:
        raise HTTPException(409,"cTrader is not authorized yet")
    access_token=fresh_access_token(str(user["id"]))
    accounts=await manager.list_accounts(access_token,row[1] or "demo")
    return {"accounts":accounts,"environment":row[1] or "demo"}

@router.post("/accounts/select")
async def select_account(body: dict,user=Depends(current_user)):
    account_id=int(body.get("account_id") or 0)
    if account_id<=0:
        raise HTTPException(400,"account_id is required")
    with connection() as conn:
        row=conn.execute(
            "SELECT access_token,environment FROM ctrader_connections WHERE user_id=%s",
            (user["id"],)
        ).fetchone()
    if not row:
        raise HTTPException(409,"cTrader is not authorized yet")
    environment=row[1] or "demo"
    if environment=="live":
        raise HTTPException(403,"Live account selection is disabled during the demo phase")
    # Verify the selected account is actually returned for this user's OAuth token.
    # Never authorize an arbitrary caller-supplied cTrader account ID.
    access_token=fresh_access_token(str(user["id"]))
    available_accounts=await manager.list_accounts(access_token,environment)
    selected=next(
        (item for item in available_accounts if int(item.get("account_id") or 0)==account_id),
        None,
    )
    if selected is None:
        raise HTTPException(403,"That cTrader account is not available to the authorized user.")
    if bool(selected.get("is_live")):
        raise HTTPException(403,"Live accounts are disabled during the demo phase.")
    await manager.authorize_account(account_id,access_token,environment)
    manager.remember_account(environment,account_id,str(user["id"]))
    with connection() as conn:
        conn.execute(
            "UPDATE ctrader_connections SET account_id=%s,updated_at=now() WHERE user_id=%s",
            (account_id,user["id"]),
        )
    return {"connected":True,"account_id":account_id,"environment":environment}

@router.get("/connection")
async def ctrader_connection(user=Depends(current_user)):
    with connection() as conn:
        row=conn.execute(
            "SELECT account_id,environment,expires_at,updated_at FROM ctrader_connections WHERE user_id=%s",
            (user["id"],)
        ).fetchone()
    if not row:
        return {"connected":False,"authorized":False}
    environment=str(row[1] or "demo")
    return {
        "connected":bool(row[0]) and manager.account_ready(environment,int(row[0])),
        "authorized":True,
        "account_id":row[0],
        "environment":environment,
        "expires_at":row[2],
        "updated_at":row[3],
    }

@router.get("/account/snapshot")
async def ctrader_account_snapshot(user=Depends(current_user)):
    """Return broker-reconciled demo account data; never substitute legacy account_state."""
    with connection() as conn:
        row=conn.execute(
            "SELECT account_id,environment FROM ctrader_connections WHERE user_id=%s",
            (user["id"],),
        ).fetchone()
    if not row or not row[0]:
        raise HTTPException(409,"Select a cTrader demo account first.")
    account_id=int(row[0])
    environment=str(row[1] or "demo").lower()
    if environment != "demo":
        raise HTTPException(403,"Live account snapshots are disabled during the demo phase.")
    if not manager.account_ready(environment,account_id):
        # Try to restore the authorized session using the user's refreshed OAuth token.
        access_token=fresh_access_token(str(user["id"]))
        await manager.authorize_account(account_id,access_token,environment)
        manager.remember_account(environment,account_id,str(user["id"]))
    if not manager.account_ready(environment,account_id):
        raise HTTPException(503,"The selected cTrader account is not connected to the cloud session.")
    state=await manager.reconcile(account_id,environment)
    trader=getattr(state,"trader",None)
    money_digits=getattr(trader,"moneyDigits",None) if trader is not None else None
    raw_balance=getattr(trader,"balance",None) if trader is not None else None
    balance=scale_balance(raw_balance,money_digits)
    symbol_names={}
    try:
        symbol_state=await manager.symbols(account_id,environment)
        for symbol in (getattr(symbol_state,"symbol",[]) or []):
            symbol_id=getattr(symbol,"symbolId",None)
            symbol_name=getattr(symbol,"symbolName",None)
            if symbol_id is not None and symbol_name:
                symbol_names[int(symbol_id)]=str(symbol_name)
    except Exception:
        # Position reconciliation remains useful if symbol metadata is temporarily unavailable.
        symbol_names={}
    positions=[]
    for position in (getattr(state,"position",[]) or []):
        trade_data=getattr(position,"tradeData",None)
        raw_side=getattr(trade_data,"tradeSide",None) if trade_data else None
        side=normalize_trade_side(raw_side)
        positions.append({
            "position_id":int(getattr(position,"positionId",0) or 0),
            "symbol_id":int(getattr(trade_data,"symbolId",0) or 0) if trade_data else None,
            "symbol":symbol_names.get(int(getattr(trade_data,"symbolId",0) or 0)) if trade_data else None,
            "volume":int(getattr(trade_data,"volume",0) or 0) if trade_data else None,
            "side":side,
            "entry_price":getattr(position,"price",None),
        })
    return {
        "provider":"cTrader Cloud",
        "environment":environment,
        "account_id":account_id,
        "source":"broker_reconcile",
        "balance":balance,
        "currency_asset_id":getattr(trader,"depositAssetId",None) if trader is not None else None,
        "positions":positions,
        "positions_count":len(positions),
        "as_of":datetime.now(timezone.utc).isoformat(),
    }

@router.get("/oauth/status")
def oauth_status(user=Depends(current_user)):
    with connection() as conn:
        row=conn.execute(
            "SELECT account_id,environment,expires_at,updated_at FROM ctrader_connections WHERE user_id=%s",
            (user["id"],)
        ).fetchone()
    if not row:
        return {"authorized":False}
    environment=str(row[1] or "demo")
    return {
        "authorized":True,
        "connected":bool(row[0]) and manager.account_ready(environment,int(row[0])),
        "account_id":row[0],
        "environment":environment,
        "expires_at":row[2],
        "updated_at":row[3],
    }
