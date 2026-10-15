"""Cloud cTrader Open API connection manager.

Uses Spotware's official Python SDK. The SDK is asynchronous over Twisted, so the
reactor is isolated in a dedicated thread while FastAPI remains asyncio-native.
"""
from __future__ import annotations

import asyncio
import math
import os
import threading
import time
import uuid
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import Any

from .db import connection


def _positive_int(value: Any, field_name: str) -> int:
    """Validate broker identifiers and volume without silently truncating values."""
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a positive integer")
    if isinstance(value, float) and (not math.isfinite(value) or not value.is_integer()):
        raise ValueError(f"{field_name} must be a positive integer")
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            raise ValueError(f"{field_name} must be a positive integer")
        try:
            parsed = int(stripped)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"{field_name} must be a positive integer") from exc
        if str(parsed) != stripped and stripped not in (f"+{parsed}",):
            raise ValueError(f"{field_name} must be a positive integer")
        result = parsed
    else:
        try:
            result = int(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"{field_name} must be a positive integer") from exc
    if result <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return result


def _positive_price(value: Any, field_name: str) -> float:
    """Reject missing, non-finite, zero, and negative protection prices."""
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a finite positive price")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field_name} must be a finite positive price") from exc
    if not math.isfinite(result) or result <= 0:
        raise ValueError(f"{field_name} must be a finite positive price")
    return result

try:
    from ctrader_open_api import Client, Protobuf, TcpProtocol, EndPoints
    from ctrader_open_api.messages.OpenApiMessages_pb2 import (
        ProtoOAApplicationAuthReq,
        ProtoOAApplicationAuthRes,
        ProtoOAErrorRes,
        ProtoOAGetAccountListByAccessTokenReq,
        ProtoOAGetAccountListByAccessTokenRes,
        ProtoOAAccountAuthReq,
        ProtoOAAccountAuthRes,
        ProtoOAReconcileReq,
        ProtoOAReconcileRes,
        ProtoOADealListReq,
        ProtoOADealListRes,
        ProtoOAAssetListReq,
        ProtoOAAssetListRes,
        ProtoOAGetPositionUnrealizedPnLReq,
        ProtoOAGetPositionUnrealizedPnLRes,
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

class CTraderManager:
    def __init__(self):
        self._sessions: dict[str, _Session] = {}
        self._symbol_cache: dict[tuple[str, int], tuple[float, Any]] = {}
        self._lock = threading.Lock()
        self._reactor_started = False
        self._reactor_thread: threading.Thread | None = None

    def available(self):
        return (
            Client is not None
            and bool(os.getenv("CTRADER_CLIENT_ID", "").strip())
            and bool(os.getenv("CTRADER_CLIENT_SECRET", "").strip())
        )

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
        # Defense in depth: no code path may open a live cTrader socket.
        if str(environment or "").strip().lower() != "demo":
            raise RuntimeError("Only cTrader demo sessions are enabled; live connections are disabled.")
        environment = "demo"
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
        try:
            req = ProtoOAApplicationAuthReq()
            req.clientId = os.getenv("CTRADER_CLIENT_ID", "").strip()
            req.clientSecret = os.getenv("CTRADER_CLIENT_SECRET", "").strip()
            d = client.send(req)
            d.addErrback(lambda failure: self._fail_all(environment, str(failure)))
        except Exception as exc:
            # A synchronous SDK failure must not leave the session waiting forever
            # for an application-auth response that will never arrive.
            self._fail_all(environment, f"cTrader application authorization could not be sent: {exc}")

    def _disconnected(self, environment, reason):
        with self._lock:
            session = self._sessions.get(environment)
            if session:
                session.ready = False
                # A reconnect is a new broker session. Do not trust account
                # authorizations from the socket that has just disconnected.
                session.accounts.clear()
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
        if payload_type == ProtoOAErrorRes().payloadType:
            data = Protobuf.extract(message)
            code = str(getattr(data, "errorCode", "unknown"))
            description = str(getattr(data, "description", "") or "").strip()
            reason = f"cTrader request failed ({code})"
            if description:
                reason = f"{reason}: {description}"
            self._resolve(environment, getattr(message, "clientMsgId", ""), error=reason)
            return
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
            # Account discovery is a response payload, not a live-session heartbeat.
            # Keep session.accounts reserved for accounts actually authorized in this session.
            self._resolve(environment, getattr(message, "clientMsgId", ""), accounts)
            return
        if payload_type == ProtoOAAccountAuthRes().payloadType:
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
        if payload_type == ProtoOADealListRes().payloadType:
            self._resolve(environment, getattr(message, "clientMsgId", ""), Protobuf.extract(message))
            return
        if payload_type == ProtoOAAssetListRes().payloadType:
            self._resolve(environment, getattr(message, "clientMsgId", ""), Protobuf.extract(message))
            return
        if payload_type == ProtoOAGetPositionUnrealizedPnLRes().payloadType:
            self._resolve(environment, getattr(message, "clientMsgId", ""), Protobuf.extract(message))
            return
        if payload_type == ProtoHeartbeatEvent().payloadType:
            return

    async def _send(self, environment: str, request, timeout: float = 15):
        if not self.available() or reactor is None:
            raise RuntimeError(
                "cTrader Open API is unavailable; check the SDK installation and client credentials"
            )
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
            try:
                d = session.client.send(request, clientMsgId=client_msg_id)
                d.addErrback(lambda failure: self._resolve(environment, client_msg_id, error=str(failure)))
            except Exception as exc:
                # Twisted send() can fail before it returns a Deferred. Resolve
                # the waiter immediately instead of leaving it until timeout.
                self._resolve(
                    environment,
                    client_msg_id,
                    error=f"cTrader request could not be sent: {exc}",
                )
        try:
            reactor.callFromThread(send)
        except Exception as exc:
            self._resolve(
                environment,
                client_msg_id,
                error=f"cTrader request could not be scheduled: {exc}",
            )
        try:
            return await asyncio.wait_for(asyncio.wrap_future(future), timeout=timeout)
        finally:
            # A timed-out request must not leave an orphaned waiter in the session.
            # Only remove our own future; a later request may reuse other message IDs.
            with self._lock:
                if session.waiters.get(client_msg_id) is future:
                    session.waiters.pop(client_msg_id, None)

    async def list_accounts(self, access_token: str, environment="demo"):
        req = ProtoOAGetAccountListByAccessTokenReq()
        req.accessToken = access_token
        return await self._send(environment, req)

    async def authorize_account(self, account_id: int, access_token: str, environment="demo"):
        if str(environment).strip().lower() != "demo":
            raise RuntimeError("Only cTrader demo accounts are enabled.")
        account_id = _positive_int(account_id, "account_id")
        req = ProtoOAAccountAuthReq()
        req.ctidTraderAccountId = account_id
        req.accessToken = access_token
        return await self._send(environment, req)

    async def reconcile(self, account_id: int, environment="demo"):
        if str(environment).strip().lower() != "demo":
            raise RuntimeError("Only cTrader demo accounts are enabled.")
        account_id = _positive_int(account_id, "account_id")
        req = ProtoOAReconcileReq()
        req.ctidTraderAccountId = account_id
        return await self._send(environment, req)


    async def deals(self, account_id: int, from_timestamp: int, to_timestamp: int, environment="demo", max_rows=1000):
        """Fetch broker execution history for a bounded UTC millisecond window."""
        if str(environment).strip().lower() != "demo":
            raise RuntimeError("Only cTrader demo accounts are enabled.")
        account_id = _positive_int(account_id, "account_id")
        from_timestamp = _positive_int(from_timestamp, "from_timestamp")
        to_timestamp = _positive_int(to_timestamp, "to_timestamp")
        max_rows = _positive_int(max_rows, "max_rows")
        if to_timestamp <= from_timestamp or to_timestamp > 2147483646000:
            raise ValueError("Invalid cTrader deal-history time window")
        if max_rows > 1000:
            raise ValueError("max_rows must not exceed 1000")
        req = ProtoOADealListReq()
        req.ctidTraderAccountId = account_id
        req.fromTimestamp = from_timestamp
        req.toTimestamp = to_timestamp
        req.maxRows = max_rows
        return await self._send(environment, req, timeout=25)

    async def assets(self, account_id: int, environment="demo"):
        """Fetch broker asset metadata for resolving the account deposit currency."""
        if str(environment).strip().lower() != "demo":
            raise RuntimeError("Only cTrader demo accounts are enabled.")
        account_id = _positive_int(account_id, "account_id")
        req = ProtoOAAssetListReq()
        req.ctidTraderAccountId = account_id
        return await self._send(environment, req, timeout=20)

    async def unrealized_pnl(self, account_id: int, environment="demo"):
        """Fetch broker-reported unrealized P/L for the selected demo account."""
        if str(environment).strip().lower() != "demo":
            raise RuntimeError("Only cTrader demo accounts are enabled.")
        account_id = _positive_int(account_id, "account_id")
        req = ProtoOAGetPositionUnrealizedPnLReq()
        req.ctidTraderAccountId = account_id
        return await self._send(environment, req, timeout=20)

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
        account_id = _positive_int(account_id, "account_id")
        normalized_environment = "live" if str(environment).lower() == "live" else "demo"
        with self._lock:
            session = self._sessions.get(normalized_environment)
            if session and session.ready:
                session.accounts[account_id] = str(user_id)

    def account_ready(self, environment: str, account_id: int) -> bool:
        """Return true only for an authorized account on a ready cTrader socket."""
        environment = "live" if str(environment).lower() == "live" else "demo"
        try:
            account_id = _positive_int(account_id, "account_id")
        except (TypeError, ValueError):
            return False
        with self._lock:
            session = self._sessions.get(environment)
            return bool(
                session
                and session.ready
                and isinstance(session.accounts, dict)
                and account_id in session.accounts
            )

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
                            "account":account_id,"heartbeat":"openapi"
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
            # Do not restore legacy live-account sessions into the cloud worker.
            if str(environment or "demo").strip().lower() != "demo":
                continue
            try:
                from .ctrader_tokens import fresh_access_token
                token=fresh_access_token(str(user_id))
                await self.authorize_account(int(account_id),token,environment or "demo")
                self.remember_account(environment or "demo",int(account_id),str(user_id))
            except Exception:
                continue


    async def symbols(self, account_id: int, environment="demo"):
        """Cache symbol metadata because snapshots refresh more frequently than symbols change."""
        if str(environment).strip().lower() != "demo":
            raise RuntimeError("Only cTrader demo accounts are enabled.")
        normalized_environment = "demo"
        account_id = _positive_int(account_id, "account_id")
        cache_key = (normalized_environment, account_id)
        now = time.monotonic()
        with self._lock:
            cached = self._symbol_cache.get(cache_key)
            if cached and now - cached[0] < 3600:
                return cached[1]
        req=ProtoOASymbolsListReq()
        req.ctidTraderAccountId=account_id
        req.includeArchivedSymbols=False
        result=await self._send(normalized_environment,req,timeout=20)
        with self._lock:
            self._symbol_cache[cache_key]=(time.monotonic(),result)
        return result

    async def new_market_order(self, account_id: int, symbol_id: int, side: str, volume: int, environment="demo"):
        if str(environment).strip().lower() != "demo":
            raise RuntimeError("Only cTrader demo accounts are enabled.")
        # Defense in depth: never translate an unknown side into a SELL order.
        normalized_side = str(side).strip().upper() if isinstance(side, str) else ""
        if normalized_side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        account_id = _positive_int(account_id, "account_id")
        symbol_id = _positive_int(symbol_id, "symbol_id")
        volume = _positive_int(volume, "volume")
        req = ProtoOANewOrderReq()
        req.ctidTraderAccountId = account_id
        req.symbolId = symbol_id
        req.orderType = ProtoOAOrderType.MARKET
        req.tradeSide = ProtoOATradeSide.BUY if normalized_side == "BUY" else ProtoOATradeSide.SELL
        req.volume = volume
        return await self._send(environment, req, timeout=20)

    async def protect_position(self, account_id: int, position_id: int, stop_loss=None, take_profit=None, environment="demo"):
        if str(environment).strip().lower() != "demo":
            raise RuntimeError("Only cTrader demo accounts are enabled.")
        account_id = _positive_int(account_id, "account_id")
        position_id = _positive_int(position_id, "position_id")
        if stop_loss is None and take_profit is None:
            raise ValueError("at least one of stop_loss or take_profit is required")
        validated_stop = _positive_price(stop_loss, "stop_loss") if stop_loss is not None else None
        validated_take = _positive_price(take_profit, "take_profit") if take_profit is not None else None
        req=ProtoOAAmendPositionSLTPReq()
        req.ctidTraderAccountId=account_id
        req.positionId=position_id
        if validated_stop is not None:
            req.stopLoss=validated_stop
        if validated_take is not None:
            req.takeProfit=validated_take
        return await self._send(environment,req,timeout=20)

    async def close_position(self, account_id: int, position_id: int, volume: int, environment="demo"):
        if str(environment).strip().lower() != "demo":
            raise RuntimeError("Only cTrader demo accounts are enabled.")
        account_id = _positive_int(account_id, "account_id")
        position_id = _positive_int(position_id, "position_id")
        volume = _positive_int(volume, "volume")
        req = ProtoOAClosePositionReq()
        req.ctidTraderAccountId = account_id
        req.positionId = position_id
        req.volume = volume
        return await self._send(environment, req, timeout=20)

manager = CTraderManager()
