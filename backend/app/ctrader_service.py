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
        ProtoOAReconcileReq,
        ProtoOAReconcileRes,
        ProtoOANewOrderReq,
        ProtoOASymbolsListReq,
        ProtoOASymbolsListRes,
        ProtoOAExecutionEvent,
        ProtoOAAmendPositionSLTPReq,
        ProtoOAAmendPositionSLTPRes,
        ProtoOAClosePositionReq,
        ProtoOAClosePositionRes,
        ProtoHeartbeatEvent,
    )
    from ctrader_open_api.messages.OpenApiModelMessages_pb2 import (
        ProtoOAOrderType,
        ProtoOATradeSide,
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

class CTraderManager:
    def __init__(self):
        self._sessions: dict[str, _Session] = {}
        self._lock = threading.Lock()
        self._reactor_started = False
        self._reactor_thread: threading.Thread | None = None

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
            self._resolve(environment, getattr(message, "clientMsgId", ""), Protobuf.extract(message))
            return
        if payload_type in (ProtoOAReconcileRes().payloadType, ProtoOANewOrderRes().payloadType, ProtoOAClosePositionRes().payloadType, ProtoOASymbolsListRes().payloadType, ProtoOAExecutionEvent().payloadType, ProtoOAAmendPositionSLTPRes().payloadType):
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
        return await asyncio.wait_for(asyncio.wrap_future(future), timeout=timeout)

    async def list_accounts(self, access_token: str, environment="demo"):
        req = ProtoOAGetAccountListByAccessTokenReq()
        req.accessToken = access_token
        return await self._send(environment, req)

    async def authorize_account(self, account_id: int, access_token: str, environment="demo"):
        req = ProtoOAAccountAuthReq()
        req.ctidTraderAccountId = int(account_id)
        req.accessToken = access_token
        return await self._send(environment, req)

    async def reconcile(self, account_id: int, environment="demo"):
        req = ProtoOAReconcileReq()
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
                token=decrypt_token(encrypted_token)
                await self.authorize_account(int(account_id),token,environment or "demo")
                self.remember_account(environment or "demo",int(account_id),str(user_id))
            except Exception:
                continue


    async def symbols(self, account_id: int, environment="demo"):
        req=ProtoOASymbolsListReq()
        req.ctidTraderAccountId=int(account_id)
        req.includeArchivedSymbols=False
        return await self._send(environment,req,timeout=20)

    async def new_market_order(self, account_id: int, symbol_id: int, side: str, volume: int, stop_loss=None, take_profit=None, environment="demo"):
        req = ProtoOANewOrderReq()
        req.ctidTraderAccountId = int(account_id)
        req.symbolId = int(symbol_id)
        req.orderType = ProtoOAOrderType.MARKET
        req.tradeSide = ProtoOATradeSide.BUY if side.upper() == "BUY" else ProtoOATradeSide.SELL
        req.volume = int(volume)
        if stop_loss is not None:
            req.stopLoss = float(stop_loss)
        if take_profit is not None:
            req.takeProfit = float(take_profit)
        return await self._send(environment, req, timeout=20)

    async def close_position(self, account_id: int, position_id: int, volume: int, environment="demo"):
        req = ProtoOAClosePositionReq()
        req.ctidTraderAccountId = int(account_id)
        req.positionId = int(position_id)
        req.volume = int(volume)
        return await self._send(environment, req, timeout=20)

manager = CTraderManager()
