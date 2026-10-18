import os
import math
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
import httpx
from fastapi import APIRouter, Depends, HTTPException
from .auth import current_user
from .db import connection
from .ctrader_security import encrypt_token
from .ctrader_service import manager
from .ctrader_tokens import _token_expiry_seconds, fresh_access_token
from .ctrader_snapshot_helpers import normalize_currency_code, normalize_trade_side, positive_integer, scale_balance, scale_unrealized_pnl
from .ctrader_metric_history import record_demo_equity_snapshot

router=APIRouter(prefix="/v1/ctrader",tags=["ctrader"])


def _assert_selected_demo_account(user_id: str, account_id: int) -> None:
    """Fail closed if the selected account changed during a broker snapshot."""
    with connection() as conn:
        selected = conn.execute(
            "SELECT account_id,environment FROM ctrader_connections WHERE user_id=%s",
            (user_id,),
        ).fetchone()
    if not selected:
        raise HTTPException(409, "The selected cTrader account changed. Refresh and retry.")
    selected_id = positive_integer(selected[0])
    selected_environment = str(selected[1] or "demo").strip().lower()
    if selected_id != account_id or selected_environment != "demo":
        raise HTTPException(409, "The selected cTrader account changed. Refresh and retry.")
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
    except ValueError as exc:
        raise HTTPException(502,"cTrader returned an unreadable token response") from exc
    if not isinstance(token,dict):
        raise HTTPException(502,"cTrader returned an invalid token response")
    if token.get("errorCode"):
        raise HTTPException(400,token.get("description") or token["errorCode"])
    access_token = token.get("accessToken")
    refresh_token = token.get("refreshToken")
    if (
        not isinstance(access_token, str)
        or not access_token.strip()
        or not isinstance(refresh_token, str)
        or not refresh_token.strip()
    ):
        raise HTTPException(502, "cTrader token response is missing required credentials")
    try:
        lifetime = _token_expiry_seconds(token.get("expiresIn", 2628000))
        expires = datetime.now(timezone.utc) + timedelta(seconds=lifetime)
    except RuntimeError as exc:
        raise HTTPException(502, "cTrader returned an invalid token expiry") from exc
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
            (user_id, encrypt_token(access_token), encrypt_token(refresh_token), expires),
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
    environment=str(row[1] or "demo").lower()
    if environment != "demo":
        raise HTTPException(403,"Only cTrader demo accounts are available during the demo phase.")
    try:
        access_token=fresh_access_token(str(user["id"]))
        accounts=await manager.list_accounts(access_token,"demo")
    except Exception as exc:
        raise HTTPException(
            503,
            "Unable to retrieve cTrader demo accounts right now. Retry shortly or reconnect cTrader authorization.",
        ) from exc
    # Never expose live accounts as selectable choices in the mobile app.
    demo_accounts=[
        item for item in accounts
        if isinstance(item,dict) and item.get("is_live") is False
    ]
    return {"accounts":demo_accounts,"environment":"demo"}

@router.post("/accounts/select")
async def select_account(body: dict,user=Depends(current_user)):
    raw_account_id = body.get("account_id")
    account_id = positive_integer(raw_account_id)
    if account_id is None:
        raise HTTPException(400, "account_id must be a positive integer")
    with connection() as conn:
        row=conn.execute(
            "SELECT access_token,environment FROM ctrader_connections WHERE user_id=%s",
            (user["id"],)
        ).fetchone()
    if not row:
        raise HTTPException(409,"cTrader is not authorized yet")
    environment=str(row[1] or "demo").strip().lower()
    if environment != "demo":
        raise HTTPException(403,"Only cTrader demo account selection is enabled.")
    # Verify the selected account is actually returned for this user's OAuth token.
    # Never authorize an arbitrary caller-supplied cTrader account ID.
    access_token=fresh_access_token(str(user["id"]))
    available_accounts=await manager.list_accounts(access_token,"demo")
    if not isinstance(available_accounts, (list, tuple)):
        raise HTTPException(503,"cTrader returned an invalid account list. Retry shortly.")
    selected=next(
        (
            item for item in available_accounts
            if isinstance(item, dict)
            and positive_integer(item.get("account_id")) == account_id
        ),
        None,
    )
    if selected is None:
        raise HTTPException(403,"That cTrader account is not available to the authorized user.")
    # Fail closed: only an explicit broker-confirmed demo flag is selectable.
    # Missing or malformed account metadata must never be treated as demo.
    if selected.get("is_live") is not False:
        raise HTTPException(403,"Only broker-confirmed cTrader demo accounts can be selected.")
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
    environment=str(row[1] or "demo").strip().lower()
    account_id=positive_integer(row[0])
    return {
        "connected":account_id is not None and environment == "demo" and manager.account_ready(environment,account_id,str(user["id"])),
        "authorized":True,
        "account_id":account_id,
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
    account_id=positive_integer(row[0])
    environment=str(row[1] or "demo").strip().lower()
    if account_id is None:
        raise HTTPException(409,"The selected cTrader account ID is invalid. Select the account again.")
    if environment != "demo":
        raise HTTPException(403,"Live account snapshots are disabled during the demo phase.")
    if not manager.account_ready(environment,account_id,str(user["id"])):
        # First recover a previously established but stale/disconnected cloud socket.
        # Then verify the saved account still belongs to this OAuth grant and is demo.
        try:
            await manager.recover_stale_sessions()
            await manager.reauthorize_selected_account(
                str(user["id"]), account_id, environment
            )
        except Exception as exc:
            # Do not return a balance until both broker session and selected account
            # have been re-authorized successfully.
            raise HTTPException(
                503,
                "Unable to verify and reconnect the selected cTrader demo account. Retry shortly or reconnect cTrader authorization.",
            ) from exc
    if not manager.account_ready(environment,account_id,str(user["id"])):
        raise HTTPException(503,"The selected cTrader account is not connected to the cloud session.")
    state=await manager.reconcile(account_id,environment)
    trader=getattr(state,"trader",None)
    money_digits=getattr(trader,"moneyDigits",None) if trader is not None else None
    raw_balance=getattr(trader,"balance",None) if trader is not None else None
    balance=scale_balance(raw_balance,money_digits)
    balance_status="broker_reconciled" if balance is not None and math.isfinite(balance) else "unavailable"
    if balance is not None and not math.isfinite(balance):
        balance=None
    raw_positions=getattr(state,"position",None)
    positions_collection_valid=isinstance(raw_positions,(list,tuple))
    positions_status="broker_reconciled" if positions_collection_valid else "unavailable"
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
    for position in (raw_positions if positions_collection_valid else []):
        trade_data=getattr(position,"tradeData",None)
        raw_side=getattr(trade_data,"tradeSide",None) if trade_data else None
        side=normalize_trade_side(raw_side)
        position_id=positive_integer(getattr(position,"positionId",None))
        symbol_id=positive_integer(getattr(trade_data,"symbolId",None)) if trade_data else None
        volume=positive_integer(getattr(trade_data,"volume",None)) if trade_data else None
        positions.append({
            "position_id":position_id,
            "symbol_id":symbol_id,
            "symbol":symbol_names.get(symbol_id) if symbol_id is not None else None,
            "volume":volume,
            "side":side,
            "entry_price":getattr(position,"price",None),
        })
    # Keep this metric explicitly unavailable unless the complete broker
    # response can be validated and scaled with cTrader's moneyDigits.
    unrealized_pnl=None
    unrealized_pnl_status="unavailable"
    try:
        pnl_state=await manager.unrealized_pnl(account_id,environment)
        pnl_digits=getattr(pnl_state,"moneyDigits",None)
        pnl_rows=getattr(pnl_state,"positionUnrealizedPnL",None)
        unrealized_pnl=scale_unrealized_pnl(pnl_rows,pnl_digits)
        if unrealized_pnl is not None:
            unrealized_pnl_status="broker_reported"
    except Exception:
        # The positions snapshot remains useful without this metric.
        pass
    equity=None
    equity_status="unavailable"
    if balance is not None and unrealized_pnl is not None:
        candidate_equity=balance+unrealized_pnl
        if math.isfinite(candidate_equity):
            equity=candidate_equity
            equity_status="derived_from_broker_balance_and_unrealized_pnl"
    snapshot_status = (
        "complete"
        if balance_status == "broker_reconciled" and positions_status == "broker_reconciled"
        else "partial"
    )

    deposit_asset_id=positive_integer(getattr(trader,"depositAssetId",None)) if trader is not None else None
    currency=None
    currency_status="unavailable"
    if deposit_asset_id is not None:
        try:
            asset_state=await manager.assets(account_id,environment)
            for asset in (getattr(asset_state,"asset",[]) or []):
                if positive_integer(getattr(asset,"assetId",None)) == deposit_asset_id:
                    asset_name=getattr(asset,"name",None)
                    if isinstance(asset_name,str) and asset_name.strip():
                        currency=asset_name.strip().upper()
                        currency_status="broker_asset_metadata"
                    break
        except Exception:
            # Never guess a currency when broker asset metadata is unavailable.
            pass
    currency = normalize_currency_code(currency)
    if currency is None:
        currency_status="unavailable"

    # Recheck after all broker awaits so an account switch cannot label stale
    # metrics or positions as belonging to the newly selected account.
    _assert_selected_demo_account(str(user["id"]), account_id)

    # Persist only complete, broker-derived metrics. This history is currently
    # observational; it must not unlock risk checks because tracking may have
    # started after an earlier equity peak.
    metric_history_status="unavailable"
    metric_history_observation=None
    observed_at=datetime.now(timezone.utc)
    if balance is not None and equity is not None and currency is not None:
        try:
            history_result=record_demo_equity_snapshot(
                user_id=str(user["id"]),
                account_id=account_id,
                environment=environment,
                balance=balance,
                equity=equity,
                currency=currency,
                observed_at=observed_at,
            )
            metric_history_status="recorded"
            metric_history_observation=history_result
        except Exception:
            # The account display must survive storage outages, but a failed
            # write never counts as persistent or verified risk history.
            metric_history_status="write_failed"

    # History persistence may take time; ensure the response still matches the
    # account selected when this snapshot began and the broker session is still fresh.
    _assert_selected_demo_account(str(user["id"]), account_id)
    if not manager.account_ready(environment, account_id, str(user["id"])):
        raise HTTPException(
            503,
            "The cTrader connection became stale while loading this snapshot. Retry to refresh the account.",
        )

    return {
        "provider":"cTrader Cloud",
        "environment":environment,
        "account_id":account_id,
        "source":"broker_reconcile",
        "snapshot_status":snapshot_status,
        "balance":balance,
        "balance_status":balance_status,
        "positions_status":positions_status,
        "unrealized_pnl":unrealized_pnl,
        "unrealized_pnl_status":unrealized_pnl_status,
        "equity":equity,
        "equity_status":equity_status,
        "today_pl":None,
        "drawdown":None,
        "risk_metrics_verified":False,
        "risk_metrics_status":"unavailable_from_current_ctrader_snapshot",
        "currency_asset_id":deposit_asset_id,
        "currency":currency,
        "currency_status":currency_status,
        "metric_history_status":metric_history_status,
        "metric_history_observation":metric_history_observation,
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
    environment=str(row[1] or "demo").strip().lower()
    account_id=positive_integer(row[0])
    return {
        "authorized":True,
        "connected":account_id is not None and environment == "demo" and manager.account_ready(environment,account_id,str(user["id"])),
        "account_id":account_id,
        "environment":environment,
        "expires_at":row[2],
        "updated_at":row[3],
    }
