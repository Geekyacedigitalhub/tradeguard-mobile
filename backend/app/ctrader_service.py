"""Cloud cTrader Open API connection manager.

Uses Spotware's official Python SDK. The SDK is asynchronous over Twisted, so the
reactor is isolated in a dedicated thread while FastAPI remains asyncio-native.
"""
from __future__ import annotations

import asyncio
import os
import threading
import uuid
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import Any

from .db import connection

try:
    from ctrader_open_api import Client, Protobuf, TcpProtocol, EndPoints
    from ctrader_open_api.messages.OpenApiMessages_pb2 import (
        ProtoOAApplicationAuthReq,
        ProtoOAApplicationAuthRes,
        ProtoOAGetAccountListByAccessTokenReq,
        ProtoOAGetAccountListByAccessTokenRes,
        ProtoOAAccountAuthReq,
        ProtoOAAccountAuthRes,
        ProtoOASymbolsListReq,
        ProtoOASymbolsListRes,
        ProtoOAReconcileReq,
        ProtoOAReconcileRes,
        ProtoOATraderReq,
        ProtoOATraderRes,
        ProtoOAGetPositionUnrealizedPnLReq,
        ProtoOAGetPositionUnrealizedPnLRes,
        ProtoOANewOrderReq,
        ProtoOAExecutionEvent,
        ProtoOAAmendPositionSLTPReq,
        ProtoOAAmendPositionSLTPRes,
        ProtoOAClosePositionReq,
        ProtoOAClosePositionRes,
        ProtoHeartbeatEvent,
        ProtoOASubscribeSpotsReq,
        ProtoOASubscribeSpotsRes,
        ProtoOAUnsubscribeSpotsReq,
        ProtoOAUnsubscribeSpotsRes,
        ProtoOASpotEvent,
        ProtoOAErrorRes,
    )
    from ctrader_open_api.messages.OpenApiModelMessages_pb2 import (
        ProtoOAOrderType,
        ProtoOATradeSide,
        ProtoOAExecutionType,
    )
    from twisted.internet import reactor
    from twisted.internet.task import LoopingCall
except ImportError:
    Client = Protobuf = TcpProtocol = EndPoints = None
    reactor = None

@dataclass
class _Session:
    client: Any
    environment: str
    ready: bool = False
    waiters: dict[str, Future] = field(default_factory=dict)
    accounts: dict[int, str] = field(default_factory=dict)
    heartbeat: Any = None
    spot_subscriptions: dict[tuple[int, int], str] = field(default_factory=dict)
    spot_waiters: dict[str, Future] = field(default_factory=dict)
    latest_spots: dict[tuple[int, int], dict[str, Any]] = field(default_factory=dict)
    authorized_accounts: set[int] = field(default_factory=set)

class CTraderManager:
    def __init__(self):
        self._sessions: dict[str, _Session] = {}
        self._lock = threading.Lock()
        self._reactor_started = False
        self._reactor_thread: threading.Thread | None = None
        self._spot_callbacks: dict[str, Any] = {}
        self._spot_lock = threading.Lock()

    def available(self):
        return Client is not None and bool(os.getenv("CTRADER_CLIENT_ID")) and bool(os.getenv("CTRADER_CLIENT_SECRET"))

    def start(self):
        if not self.available() or self._reactor_started:
            return
        self._reactor_started = True
        def run():
            reactor.run(installSignalHandlers=False)
        self._reactor_thread = threading.Thread(target=run, name="ctrader-reactor", daemon=True)
        self._reactor_thread.start()

    def stop(self):
        if reactor is not None and self._reactor_started and getattr(reactor, "running", False):
            reactor.callFromThread(reactor.stop)

    def _session(self, environment: str) -> _Session:
        environment = "live" if environment == "live" else "demo"
        with self._lock:
            existing = self._sessions.get(environment)
            if existing:
                return existing
            host = EndPoints.PROTOBUF_LIVE_HOST if environment == "live" else EndPoints.PROTOBUF_DEMO_HOST
            client = Client(host, EndPoints.PROTOBUF_PORT, TcpProtocol)
            session = _Session(client=client, environment=environment)
            self._sessions[environment] = session
        client.setConnectedCallback(lambda c: self._connected(environment, c))
        client.setDisconnectedCallback(lambda c, reason: self._disconnected(environment, reason))
        client.setMessageReceivedCallback(lambda c, msg: self._message(environment, c, msg))
        reactor.callFromThread(client.startService)
        return session

    def _connected(self, environment, client):
        req = ProtoOAApplicationAuthReq()
        req.clientId = os.getenv("CTRADER_CLIENT_ID", "")
        req.clientSecret = os.getenv("CTRADER_CLIENT_SECRET", "")
        d = client.send(req)
        d.addErrback(lambda failure: self._fail_all(environment, str(failure)))

    def _disconnected(self, environment, reason):
        with self._lock:
            session = self._sessions.get(environment)
            if session:
                session.ready = False
                session.authorized_accounts.clear()
                session.spot_subscriptions.clear()
                session.latest_spots.clear()
        # Any active mobile socket must stop showing stale broker data until
        # a fresh authenticated subscription is established.
        with self._spot_lock:
            callbacks = list(self._spot_callbacks.values())
        for callback in callbacks:
            try:
                callback({"type":"stream_error","provider":"ctrader","message":f"cTrader disconnected: {str(reason)[:120]}"})
            except Exception:
                pass
        self._fail_all(environment, f"cTrader disconnected: {reason}")

    def _fail_all(self, environment, reason):
        with self._lock:
            session = self._sessions.get(environment)
            waiters = list(session.waiters.values()) if session else []
            if session:
                session.waiters.clear()
        for future in waiters:
            if not future.done():
                future.set_exception(RuntimeError(reason))

    def _resolve(self, environment, client_msg_id, value=None, error=None):
        with self._lock:
            session = self._sessions.get(environment)
            future = session.waiters.pop(client_msg_id, None) if session else None
        if future and not future.done():
            if error:
                future.set_exception(RuntimeError(error))
            else:
                future.set_result(value)

    def _message(self, environment, client, message):
        payload_type = message.payloadType
        if payload_type == ProtoOAApplicationAuthRes().payloadType:
            with self._lock:
                session = self._sessions.get(environment)
                if session:
                    session.ready = True
            return
        if payload_type == ProtoOAGetAccountListByAccessTokenRes().payloadType:
            data = Protobuf.extract(message)
            accounts = []
            for item in getattr(data, "ctidTraderAccount", []):
                accounts.append({
                    "account_id": int(item.ctidTraderAccountId),
                    "is_live": bool(getattr(item, "isLive", False)),
                    "trader_login": int(getattr(item, "traderLogin", 0) or 0),
                })
            with self._lock:
                session = self._sessions.get(environment)
                if session:
                    session.accounts = accounts
            self._resolve(environment, getattr(message, "clientMsgId", ""), accounts)
            return
        if payload_type == ProtoOAAccountAuthRes().payloadType:
            data = Protobuf.extract(message)
            account_id = int(getattr(data, "ctidTraderAccountId", 0) or 0)
            with self._lock:
                session = self._sessions.get(environment)
                if session and account_id > 0:
                    session.authorized_accounts.add(account_id)
            self._resolve(environment, getattr(message, "clientMsgId", ""), data)
            return
        if payload_type == ProtoOAErrorRes().payloadType:
            data = Protobuf.extract(message)
            error_code = str(getattr(data, "errorCode", "Unknown cTrader API error"))
            description = str(getattr(data, "description", "") or "")
            message_text = f"cTrader API error {error_code}: {description}".strip()
            self._resolve(environment, getattr(message, "clientMsgId", ""), error=message_text)
            return
        if payload_type == ProtoOATraderRes().payloadType:
            self._resolve(environment, getattr(message, "clientMsgId", ""), Protobuf.extract(message))
            return
        if payload_type == ProtoOAGetPositionUnrealizedPnLRes().payloadType:
            self._resolve(environment, getattr(message, "clientMsgId", ""), Protobuf.extract(message))
            return
        if payload_type == ProtoOASpotEvent().payloadType:
            data = Protobuf.extract(message)
            account_id = int(getattr(data, "ctidTraderAccountId", 0) or 0)
            symbol_id = int(getattr(data, "symbolId", 0) or 0)
            if not account_id or not symbol_id:
                return
            with self._lock:
                session = self._sessions.get(environment)
                user_id = session.spot_subscriptions.get((account_id, symbol_id)) if session else None
                spot = None
                if session:
                    previous = session.latest_spots.get((account_id, symbol_id), {})
                    spot = dict(previous)
                    # In the official protocol these values are optional; do
                    # not emit a tick until at least one valid side is present.
                    if getattr(data, "bid", None) is not None and float(data.bid) > 0:
                        spot["bid"] = float(data.bid) / 100000
                    if getattr(data, "ask", None) is not None and float(data.ask) > 0:
                        spot["ask"] = float(data.ask) / 100000
                    if getattr(data, "timestamp", None) is not None:
                        spot["timestamp"] = int(data.timestamp)
                    if spot.get("bid") or spot.get("ask"):
                        session.latest_spots[(account_id, symbol_id)] = spot
                    else:
                        spot = None
            if user_id and spot:
                with self._spot_lock:
                    callback = self._spot_callbacks.get(user_id)
                if callback:
                    try:
                        bid = spot.get("bid")
                        ask = spot.get("ask")
                        callback({
                            "type": "tick", "provider": "ctrader", "symbol_id": symbol_id,
                            "bid": bid, "ask": ask,
                            "price": (bid + ask) / 2 if bid and ask else bid or ask,
                            "time": spot.get("timestamp"), "time_msc": spot.get("timestamp"),
                        })
                    except Exception:
                        pass
            return
        if payload_type == ProtoOASubscribeSpotsRes().payloadType:
            self._resolve(environment, getattr(message, "clientMsgId", ""), Protobuf.extract(message))
            return
        if payload_type == ProtoOAUnsubscribeSpotsRes().payloadType:
            self._resolve(environment, getattr(message, "clientMsgId", ""), Protobuf.extract(message))
            return
        if payload_type == ProtoOAExecutionEvent().payloadType:
            data=Protobuf.extract(message)
            if getattr(data,"executionType",None) == ProtoOAExecutionType.ORDER_FILLED or getattr(data,"errorCode",""):
                self._resolve(environment,getattr(message,"clientMsgId",""),data)
            return
        if payload_type in (ProtoOAReconcileRes().payloadType, ProtoOAClosePositionRes().payloadType, ProtoOASymbolsListRes().payloadType, ProtoOAAmendPositionSLTPRes().payloadType):
            self._resolve(environment, getattr(message, "clientMsgId", ""), Protobuf.extract(message))
            return
        if payload_type == ProtoHeartbeatEvent().payloadType:
            return

    async def _send(self, environment: str, request, timeout: float = 15):
        self.start()
        session = self._session(environment)
        for _ in range(30):
            with self._lock:
                ready = session.ready
            if ready:
                break
            await asyncio.sleep(0.5)
        if not session.ready:
            raise RuntimeError(f"cTrader {environment} connection is not ready")
        client_msg_id = uuid.uuid4().hex
        future: Future = Future()
        with self._lock:
            session.waiters[client_msg_id] = future
        def send():
            d = session.client.send(request, clientMsgId=client_msg_id)
            d.addErrback(lambda failure: self._resolve(environment, client_msg_id, error=str(failure)))
        reactor.callFromThread(send)
        try:
            return await asyncio.wait_for(asyncio.wrap_future(future), timeout=timeout)
        finally:
            with self._lock:
                session = self._sessions.get(environment)
                if session:
                    session.waiters.pop(client_msg_id, None)
                    # Expire waiters that timed out or were cancelled. The
                    # response may arrive later, but must not leak a Future.
                    for key, waiter in list(session.waiters.items()):
                        if waiter.done():
                            session.waiters.pop(key, None)

    async def list_accounts(self, access_token: str, environment="demo"):
        req = ProtoOAGetAccountListByAccessTokenReq()
        req.accessToken = access_token
        result = await self._send(environment, req)
        if isinstance(result, dict):
            error_code = result.get("errorCode") or result.get("error_code")
            if error_code:
                raise RuntimeError(f"cTrader account list error: {error_code}")
        return result

    async def authorize_account(self, account_id: int, access_token: str, environment="demo"):
        environment = "live" if environment == "live" else "demo"
        account_id = int(account_id)
        session = self._session(environment)
        with self._lock:
            if account_id in session.authorized_accounts:
                return {"ctidTraderAccountId":account_id,"authorized":True,"cached":True}
        req = ProtoOAAccountAuthReq()
        req.ctidTraderAccountId = account_id
        req.accessToken = access_token
        result = await self._send(environment, req)
        with self._lock:
            session.authorized_accounts.add(account_id)
        return result

    def register_spot_callback(self, user_id: str, callback):
        with self._spot_lock:
            self._spot_callbacks[str(user_id)] = callback

    def unregister_spot_callback(self, user_id: str, callback=None):
        user_id = str(user_id)
        with self._spot_lock:
            current = self._spot_callbacks.get(user_id)
            if current is not None and (callback is None or current is callback):
                self._spot_callbacks.pop(user_id, None)

    async def subscribe_spots(self, user_id: str, account_id: int, symbol_id: int, access_token: str, environment="demo"):
        environment = "live" if environment == "live" else "demo"
        session = self._session(environment)
        account_id = int(account_id)
        key = (account_id, int(symbol_id))
        with self._lock:
            owner = session.spot_subscriptions.get(key)
            authorized = account_id in session.authorized_accounts
            if owner and owner != str(user_id):
                raise RuntimeError("Spot subscription key is already assigned to another user")
            if owner == str(user_id):
                return session.latest_spots.get(key)
        # The stream route authorizes once before subscribing to many symbols.
        # Re-authorize only when this connection has not yet authorized the account.
        if not authorized:
            await self.authorize_account(account_id, access_token, environment)
            with self._lock:
                authorized = account_id in session.authorized_accounts
            if not authorized:
                raise RuntimeError("cTrader account authorization was not confirmed")
        req = ProtoOASubscribeSpotsReq()
        req.ctidTraderAccountId = int(account_id)
        req.symbolId.append(int(symbol_id))
        req.subscribeToSpotTimestamp = True
        await self._send(environment, req, timeout=20)
        with self._lock:
            session.spot_subscriptions[key] = str(user_id)
        return session.latest_spots.get(key)

    async def unsubscribe_spots(self, user_id: str, account_id: int, symbol_id: int, environment="demo"):
        environment = "live" if environment == "live" else "demo"
        session = self._sessions.get(environment)
        if not session:
            return
        key = (int(account_id), int(symbol_id))
        with self._lock:
            if session.spot_subscriptions.get(key) != str(user_id):
                return
        req = ProtoOAUnsubscribeSpotsReq()
        req.ctidTraderAccountId = int(account_id)
        req.symbolId.append(int(symbol_id))
        await self._send(environment, req, timeout=15)
        with self._lock:
            # Remove routing only after the broker acknowledged unsubscribe.
            session.spot_subscriptions.pop(key, None)
            session.latest_spots.pop(key, None)

    async def reconcile(self, account_id: int, environment="demo"):
        req = ProtoOAReconcileReq()
        req.ctidTraderAccountId = int(account_id)
        return await self._send(environment, req)

    async def trader(self, account_id: int, environment="demo"):
        req = ProtoOATraderReq()
        req.ctidTraderAccountId = int(account_id)
        return await self._send(environment, req)

    async def unrealized_pnl(self, account_id: int, environment="demo"):
        req = ProtoOAGetPositionUnrealizedPnLReq()
        req.ctidTraderAccountId = int(account_id)
        return await self._send(environment, req)


    def _send_heartbeat(self, environment):
        with self._lock:
            session=self._sessions.get(environment)
            if not session or not session.ready:
                return
        try:
            session.client.send(ProtoHeartbeatEvent())
        except Exception:
            pass

    def remember_account(self, environment: str, account_id: int, user_id: str):
        with self._lock:
            session=self._sessions.get(environment)
            if session:
                session.accounts[int(account_id)]=str(user_id)

    def heartbeat_snapshot(self):
        rows=[]
        with self._lock:
            sessions=list(self._sessions.items())
            for environment,session in sessions:
                if not session.ready:
                    continue
                for account_id,user_id in session.accounts.items():
                    rows.append((environment,account_id,user_id))
        now=__import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        if rows:
            with connection() as conn:
                for environment,account_id,user_id in rows:
                    conn.execute(
                        "INSERT INTO audit_events (user_id,event_type,payload) VALUES (%s,'broker_connection',%s::jsonb)",
                        (user_id,__import__("json").dumps({
                            "connected":True,"terminal":"cTrader Cloud","provider":"cTrader","environment":environment,
                            "account":account_id,"positions":[],"heartbeat":"openapi"
                        }))
                    )
        return rows

    async def restore_from_db(self):
        with connection() as conn:
            rows=conn.execute(
                "SELECT user_id,account_id,environment,access_token FROM ctrader_connections WHERE account_id IS NOT NULL AND access_token IS NOT NULL"
            ).fetchall()
        if not rows:
            return
        from .ctrader_security import decrypt_token
        for user_id,account_id,environment,encrypted_token in rows:
            try:
                from .ctrader_tokens import fresh_access_token
                token=fresh_access_token(str(user_id))
                await self.authorize_account(int(account_id),token,environment or "demo")
                self.remember_account(environment or "demo",int(account_id),str(user_id))
            except Exception:
                continue


    async def symbols(self, account_id: int, environment="demo"):
        req=ProtoOASymbolsListReq()
        req.ctidTraderAccountId=int(account_id)
        req.includeArchivedSymbols=False
        return await self._send(environment,req,timeout=20)

    async def symbol_volume_units(self, account_id: int, symbol_id: int, environment="demo"):
        """Return raw cTrader volume constraints for future verified risk sizing.

        Raw protocol volumes are hundredths of a unit (100 = 1 unit on SDK
        instruments that express volume in units). This reports broker metadata
        only; callers must still convert target risk into volume using actual
        pip value and account-currency conversion before submitting an order.
        """
        symbols = await self.symbols(account_id, environment)
        symbol = next(
            (item for item in getattr(symbols, "symbol", [])
             if int(getattr(item, "symbolId", 0) or 0) == int(symbol_id)),
            None,
        )
        if symbol is None:
            raise RuntimeError(f"cTrader symbol id {symbol_id} is not available")
        return {
            "symbol_id": int(symbol_id),
            "symbol_name": str(getattr(symbol, "symbolName", "")),
            "digits": int(getattr(symbol, "digits", 0) or 0),
            "lot_size": int(getattr(symbol, "lotSize", 0) or 0),
            "min_volume": int(getattr(symbol, "minVolume", 0) or 0),
            "max_volume": int(getattr(symbol, "maxVolume", 0) or 0),
            "step_volume": int(getattr(symbol, "stepVolume", 0) or 0),
            "volume_is_raw_protocol_units": True,
            "risk_sizing_verified": False,
        }

    async def new_market_order(self, account_id: int, symbol_id: int, side: str, volume: int, environment="demo"):
        if int(volume) <= 0:
            raise ValueError("cTrader order volume must be a positive broker protocol integer")
        if side.upper() not in ("BUY", "SELL"):
            raise ValueError("cTrader order side must be BUY or SELL")
        req = ProtoOANewOrderReq()
        req.ctidTraderAccountId = int(account_id)
        req.symbolId = int(symbol_id)
        req.orderType = ProtoOAOrderType.MARKET
        req.tradeSide = ProtoOATradeSide.BUY if side.upper() == "BUY" else ProtoOATradeSide.SELL
        req.volume = int(volume)
        return await self._send(environment, req, timeout=20)

    async def protect_position(self, account_id: int, position_id: int, stop_loss=None, take_profit=None, environment="demo"):
        req=ProtoOAAmendPositionSLTPReq()
        req.ctidTraderAccountId=int(account_id)
        req.positionId=int(position_id)
        if stop_loss is not None:
            req.stopLoss=float(stop_loss)
        if take_profit is not None:
            req.takeProfit=float(take_profit)
        return await self._send(environment,req,timeout=20)

    async def close_position(self, account_id: int, position_id: int, volume: int, environment="demo"):
        if int(position_id) <= 0 or int(volume) <= 0:
            raise ValueError("cTrader close requires positive position id and broker protocol volume")
        req = ProtoOAClosePositionReq()
        req.ctidTraderAccountId = int(account_id)
        req.positionId = int(position_id)
        req.volume = int(volume)
        return await self._send(environment, req, timeout=20)

manager = CTraderManager()
