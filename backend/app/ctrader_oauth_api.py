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
import asyncio
from fastapi import WebSocket, WebSocketDisconnect

router=APIRouter(prefix="/v1/ctrader",tags=["ctrader"])
CLIENT_ID=os.getenv("CTRADER_CLIENT_ID","").strip()
CLIENT_SECRET=os.getenv("CTRADER_CLIENT_SECRET","").strip()
REDIRECT_URI=os.getenv("CTRADER_REDIRECT_URI","https://tradeguard-api.fastapicloud.dev/v1/ctrader/oauth/callback").strip()


def _require_config():
    if not CLIENT_ID or not CLIENT_SECRET:
        raise HTTPException(503,"cTrader Open API credentials are not configured")


def _connection_row(user_id):
    with connection() as conn:
        return conn.execute(
            "SELECT access_token,environment,account_id,expires_at,updated_at FROM ctrader_connections WHERE user_id=%s",
            (user_id,),
        ).fetchone()


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
    with connection() as conn:
        row=conn.execute(
            """SELECT payload,created_at FROM audit_events
               WHERE user_id=%s AND event_type='ctrader_oauth_state'
               ORDER BY created_at DESC LIMIT 1""",(user_id,)
        ).fetchone()
    if not row or (row[0] or {}).get("state")!=state:
        raise HTTPException(400,"OAuth state is invalid or expired")
    created_at=row[1]
    if created_at.tzinfo is None:
        created_at=created_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc)-created_at > timedelta(minutes=10):
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
    if not token.get("accessToken") or not token.get("refreshToken"):
        raise HTTPException(502,"cTrader authorization returned incomplete tokens")
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
            (user_id,encrypt_token(token["accessToken"]),encrypt_token(token["refreshToken"]),expires),
        )
    return {"connected":True,"message":"cTrader authorization completed. Return to TradeGuard and refresh accounts."}


@router.get("/accounts")
async def accounts(user=Depends(current_user)):
    row=_connection_row(user["id"])
    if not row:
        raise HTTPException(409,"cTrader is not authorized yet")
    access_token=fresh_access_token(str(user["id"]))
    # cTrader account-list authorization is account-token scoped. The same
    # access token can enumerate accounts from either account environment.
    results=[]
    errors=[]
    # The account-list request is bound to whichever Open API environment the
    # account-list response identifies. Query both endpoints and merge by ID;
    # a valid Demo account must not hide a Live account (or vice versa).
    for environment in ("demo","live"):
        try:
            results.extend(await manager.list_accounts(access_token,environment))
        except Exception as exc:
            errors.append(f"{environment}: {str(exc)[:120]}")
    if not results and errors:
        raise HTTPException(503,"Could not retrieve cTrader accounts: "+"; ".join(errors))
    normalized=[]
    for value in results:
        item=dict(value)
        item["environment"]="live" if item.get("is_live") else "demo"
        normalized.append(item)
    unique={int(item["account_id"]):item for item in normalized if item.get("account_id")}
    if not unique and errors:
        raise HTTPException(503,"Could not retrieve cTrader accounts: "+"; ".join(errors))
    selected_id=row[2]
    return {
        "accounts":sorted(unique.values(),key=lambda x:(x["environment"],x["account_id"])),
        "selected_account_id":int(selected_id) if selected_id else None,
        "environment":row[1] or "demo",
    }


@router.post("/accounts/select")
async def select_account(body: dict,user=Depends(current_user)):
    try:
        account_id=int(body.get("account_id") or 0)
    except (TypeError,ValueError):
        account_id=0
    if account_id<=0:
        raise HTTPException(400,"A valid cTrader account_id is required")
    row=_connection_row(user["id"])
    if not row:
        raise HTTPException(409,"cTrader is not authorized yet")
    access_token=fresh_access_token(str(user["id"]))
    candidates=[]
    errors=[]
    for host_environment in ("demo","live"):
        try:
            candidates.extend(await manager.list_accounts(access_token,host_environment))
        except Exception as exc:
            errors.append(str(exc)[:100])
    if not candidates and errors:
        raise HTTPException(503,"Could not retrieve authorized cTrader accounts.")
    item=next((dict(value) for value in candidates if int(value.get("account_id") or 0)==account_id),None)
    if item is None:
        raise HTTPException(403,"That account was not returned by your authorized cTrader identity. Refresh accounts and try again.")
    environment="live" if item.get("is_live") else "demo"
    await manager.authorize_account(account_id,access_token,environment)
    manager.remember_account(environment,account_id,str(user["id"]))
    with connection() as conn:
        conn.execute(
            "UPDATE ctrader_connections SET account_id=%s,environment=%s,updated_at=now() WHERE user_id=%s",
            (account_id,environment,user["id"]),
        )
    return {"connected":True,"account_id":account_id,"environment":environment,"is_live":environment=="live"}


@router.get("/connection")
async def ctrader_connection(user=Depends(current_user)):
    row=_connection_row(user["id"])
    if not row:
        return {"connected":False,"authorized":False,"account_id":None,"environment":None}
    return {
        "connected":bool(row[2]),"authorized":bool(row[0]),"account_id":int(row[2]) if row[2] else None,
        "environment":row[1] or "demo","expires_at":row[3],"updated_at":row[4],
        "automated_execution_allowed":bool(row[2]) and row[1]=="demo",
    }


@router.get("/oauth/status")
def oauth_status(user=Depends(current_user)):
    row=_connection_row(user["id"])
    if not row:
        return {"authorized":False,"account_id":None,"environment":None}
    return {
        "authorized":bool(row[0]),"account_id":int(row[2]) if row[2] else None,
        "environment":row[1] or "demo","expires_at":row[3],"updated_at":row[4],
    }


@router.get("/account")
async def ctrader_account(user=Depends(current_user)):
    """Return verified broker account metrics; never substitute paper defaults."""
    row=_connection_row(user["id"])
    if not row or not row[0] or not row[2]:
        return {"connected":False,"authorized":bool(row and row[0]),"account_id":None,"environment":row[1] if row else None}
    environment=row[1] or "demo"
    try:
        token=fresh_access_token(str(user["id"]))
        await manager.authorize_account(int(row[2]),token,environment)
        trader_response=await manager.trader(int(row[2]),environment)
        trader=getattr(trader_response,"trader",None)
        if trader is None:
            raise RuntimeError("cTrader did not return trader account metadata")
        reconcile=await manager.reconcile(int(row[2]),environment)
        deposit_asset_id=int(getattr(trader,"depositAssetId",0) or 0)
        currency=None
        try:
            assets_response=await manager.assets(int(row[2]),environment)
            deposit_asset=next(
                (asset for asset in getattr(assets_response,"asset",[])
                 if int(getattr(asset,"assetId",0) or 0)==deposit_asset_id),
                None,
            )
            if deposit_asset is not None:
                currency=str(getattr(deposit_asset,"name","") or getattr(deposit_asset,"displayName","") or "") or None
        except Exception:
            # Do not guess the account currency if broker asset metadata is unavailable.
            currency=None
        money_digits=int(getattr(trader,"moneyDigits",2) or 0)
        money_scale=10**money_digits
        balance=float(getattr(trader,"balance",0))/money_scale
        positions=[]
        symbols_by_id={}
        try:
            symbols_response=await manager.symbols(int(row[2]),environment)
            symbols_by_id={int(s.symbolId):str(s.symbolName) for s in getattr(symbols_response,"symbol",[])}
        except Exception:
            # Account balances and position IDs remain real even if symbol
            # metadata briefly fails; unknown symbols are labeled by ID.
            symbols_by_id={}
        position_rows=getattr(reconcile,"position",[])
        for p in position_rows:
            trade_data=getattr(p,"tradeData",None)
            symbol_id=int(getattr(trade_data,"symbolId",0) or 0)
            positions.append({
                "position_id":int(getattr(p,"positionId",0) or 0),
                "symbol":symbols_by_id.get(symbol_id,f"SYMBOL-{symbol_id}"),
                "symbol_id":symbol_id,
                "side":"BUY" if int(getattr(trade_data,"tradeSide",1) or 1)==1 else "SELL",
                "volume_protocol_units":int(getattr(trade_data,"volume",0) or 0),
                "entry_price":float(getattr(p,"price",0) or 0),
                "stop_loss":getattr(p,"stopLoss",None),
                "take_profit":getattr(p,"takeProfit",None),
                "swap":float(getattr(p,"swap",0) or 0)/money_scale,
            })
        pnl_response=await manager.unrealized_pnl(int(row[2]),environment)
        # cTrader deal timestamps are Unix milliseconds. Define this metric on
        # a UTC calendar day and never silently return a partial history result.
        now_utc=datetime.now(timezone.utc)
        day_start=now_utc.replace(hour=0,minute=0,second=0,microsecond=0)
        today_pl=None
        try:
            deals_response=await manager.deals(
                int(row[2]),int(day_start.timestamp()*1000),int(now_utc.timestamp()*1000),environment,max_rows=1000
            )
            if not bool(getattr(deals_response,"hasMore",False)):
                realized=0.0
                pnl_complete=True
                for deal in getattr(deals_response,"deal",[]):
                    detail=getattr(deal,"closePositionDetail",None)
                    if detail is None:
                        continue
                    digits=int(getattr(detail,"moneyDigits",getattr(deal,"moneyDigits",money_digits)) or 0)
                    scale=10**digits
                    realized += (
                        float(getattr(detail,"grossProfit",0) or 0)
                        + float(getattr(detail,"swap",0) or 0)
                        + float(getattr(detail,"commission",0) or 0)
                        - float(getattr(detail,"pnlConversionFee",0) or 0)
                    )/scale
                today_pl=realized
        except Exception:
            # Balance and equity remain available; never substitute a guessed P/L.
            today_pl=None
        pnl_digits=int(getattr(pnl_response,"moneyDigits",money_digits) or 0)
        pnl_scale=10**pnl_digits
        pnl_rows=getattr(pnl_response,"positionUnrealizedPnL",[])
        unrealized_pnl=sum(float(getattr(item,"netUnrealizedPnL",0) or 0)/pnl_scale for item in pnl_rows)
        equity=balance+unrealized_pnl
        # cTrader trader metadata in this SDK exposes balance but not free margin.
        # Do not infer margin values; report them explicitly as unavailable.
        free_margin=None
        used_margin=None
        return {
            "connected":True,"authorized":True,"account_id":int(row[2]),"environment":environment,
            "is_live":environment=="live","trader_login":int(getattr(trader,"traderLogin",0) or 0),
            "broker_name":str(getattr(trader,"brokerName","") or ""),
            "currency_asset_id":int(getattr(trader,"depositAssetId",0) or 0),
            "money_digits":money_digits,
            "balance":balance,"equity":equity,"today_pl":today_pl,"drawdown":None,"today_pl_timezone":"UTC",
            "unrealized_pnl":unrealized_pnl,"free_margin":free_margin,"used_margin":used_margin,
            "currency":currency,"positions_count":len(positions),"positions":positions,
            "updated_at":datetime.now(timezone.utc).isoformat(),
            "data_source":"ctrader_open_api","automated_execution_allowed":environment=="demo",
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(503,f"Could not fetch the selected cTrader account snapshot: {str(exc)[:180]}")


@router.websocket("/market-stream")
async def ctrader_market_stream(websocket: WebSocket):
    """Stream real cTrader spot events for the user's selected account."""
    token = websocket.query_params.get("token")
    try:
        if not token:
            raise ValueError("missing token")
        from .auth import _decode_token
        user_id = str(_decode_token(token))
    except Exception:
        await websocket.close(code=1008, reason="Invalid authentication token")
        return

    try:
        row = _connection_row(user_id)
    except Exception:
        row = None
    if not row or not row[0] or not row[2]:
        await websocket.close(code=1008, reason="A selected cTrader account is required")
        return

    account_id = int(row[2])
    environment = "live" if str(row[1] or "demo").lower() == "live" else "demo"
    await websocket.accept()
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    # Used to avoid reporting a WebSocket as live until the broker actually
    # publishes a tick, and to avoid leaked tasks on mobile backgrounding.
    stream_tasks = set()
    symbol_names = {}
    subscribed_ids = []

    def enqueue(payload):
        # Translate cTrader symbol ids back into names consumed by PriceChart.
        symbol_id = int(payload.get("symbol_id") or 0)
        payload = {**payload, "symbol": symbol_names.get(symbol_id, f"SYMBOL-{symbol_id}")}
        def put():
            if stopped.is_set():
                return
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                pass
        loop.call_soon_threadsafe(put)

    ctrader_manager_callback = enqueue
    try:
        access_token = fresh_access_token(user_id)
        await manager.authorize_account(account_id, access_token, environment)
        # Do not overwrite a user's existing subscription callback when a
        # second app screen reconnects; this socket owns this callback only.
        symbols_response = await manager.symbols(account_id, environment)
        all_symbols = [
            (int(getattr(item, "symbolId", 0) or 0), str(getattr(item, "symbolName", "")))
            for item in getattr(symbols_response, "symbol", [])
            if int(getattr(item, "symbolId", 0) or 0) > 0
        ]
        # Subscribe to the app's supported market universe, not every symbol
        # in a broker's catalogue (which can be thousands of instruments).
        from .main import MARKETS
        supported = {''.join(ch for ch in value.upper() if ch.isalnum()) for value in MARKETS}
        symbols = [
            (symbol_id, name) for symbol_id, name in all_symbols
            if ''.join(ch for ch in name.upper() if ch.isalnum()) in supported
        ]
        if not symbols:
            raise RuntimeError("None of TradeGuard's supported markets are available on this cTrader account")
        symbol_names.update({symbol_id: name for symbol_id, name in symbols})
        manager.register_spot_callback(user_id, ctrader_manager_callback)
        for symbol_id, _ in symbols:
            await manager.subscribe_spots(user_id, account_id, symbol_id, access_token, environment)
            subscribed_ids.append(symbol_id)
        await websocket.send_json({
            "type": "subscribed",
            "provider": "ctrader",
            "account_id": account_id,
            "environment": environment,
            "symbols": len(subscribed_ids),
        })

        async def send_ticks():
            while not stopped.is_set():
                payload = await queue.get()
                await websocket.send_json(payload)

        async def receive_client_frames():
            while not stopped.is_set():
                await websocket.receive_text()

        sender = asyncio.create_task(send_ticks())
        receiver = asyncio.create_task(receive_client_frames())
        stream_tasks = {sender, receiver}
        done, pending = await asyncio.wait(stream_tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            task.result()
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        try:
            await websocket.send_json({"type": "stream_error", "provider": "ctrader", "message": str(exc)[:160]})
        except Exception:
            pass
    finally:
        stopped.set()
        manager.unregister_spot_callback(user_id, ctrader_manager_callback)
        for task in stream_tasks:
            if not task.done():
                task.cancel()
        if stream_tasks:
            await asyncio.gather(*stream_tasks, return_exceptions=True)
        for symbol_id in subscribed_ids:
            try:
                await manager.unsubscribe_spots(user_id, account_id, symbol_id, environment)
            except Exception:
                pass
