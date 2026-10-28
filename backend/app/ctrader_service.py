"""Cloud cTrader Open API connection manager.

Uses Spotware's official Python SDK. The SDK is asynchronous over Twisted, so the
reactor is isolated in a dedicated thread while FastAPI remains asyncio-native.
"""
from __future__ import annotations

import asyncio
import os
import threading
import time
import uuid
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import Any
import math

from .db import connection
from .ctrader_volume_validation import validate_protocol_volume, validate_symbol_volume_metadata
from .ctrader_protection_validation import validate_protection_request, validate_positive_identifier, validate_deal_window
from .ctrader_conversion import normalize_conversion_symbols, quotes_from_spot_snapshot


def is_fill_execution(execution_type: Any, *, filled_type: Any, partial_fill_type: Any = None) -> bool:
    """Only full/partial fill events qualify as fill evidence, never acceptance alone."""
    return execution_type == filled_type or (
        partial_fill_type is not None and execution_type == partial_fill_type
    )


def decode_spot_price(raw_price: Any, digits: Any) -> float | None:
    """Convert cTrader integer spot prices using strict protocol values."""
    if (
        isinstance(raw_price, bool)
        or not isinstance(raw_price, int)
        or raw_price <= 0
        or isinstance(digits, bool)
        or not isinstance(digits, int)
        or digits < 0
        or digits > 12
    ):
        return None
    return raw_price / (10 ** digits)


def build_spot_tick_payload(account_id: int, symbol_id: int, spot: dict[str, Any]) -> dict[str, Any]:
    """Build a broker tick with its account identity preserved for stream isolation."""
    bid = spot.get("bid")
    ask = spot.get("ask")
    return {
        "type": "tick",
        "provider": "ctrader",
        "account_id": int(account_id),
        "symbol_id": int(symbol_id),
        "bid": bid,
        "ask": ask,
        "price": (bid + ask) / 2 if bid is not None and ask is not None else bid if bid is not None else ask,
        "time": spot.get("timestamp"),
        "time_msc": spot.get("timestamp"),
    }


def filter_spot_tick_for_stream(payload: dict[str, Any], account_id: int, symbol_names: dict[int, str]) -> dict[str, Any] | None:
    """Reject ticks outside this socket's selected account and subscriptions."""
    raw_account_id = payload.get("account_id")
    raw_symbol_id = payload.get("symbol_id")

    def strict_identifier(value):
        # JSON booleans and floats must not be truncated/coerced into broker IDs.
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value if value > 0 else None
        if isinstance(value, str) and value.isascii() and value.isdigit():
            parsed = int(value)
            return parsed if parsed > 0 else None
        return None

    parsed_account_id = strict_identifier(raw_account_id)
    parsed_expected_account_id = strict_identifier(account_id)
    symbol_id = strict_identifier(raw_symbol_id)
    if (
        parsed_account_id is None
        or parsed_expected_account_id is None
        or symbol_id is None
        or parsed_account_id != parsed_expected_account_id
    ):
        return None
    symbol = symbol_names.get(symbol_id)
    if not symbol:
        return None
    return {**payload, "symbol": symbol}


def merge_spot_quote(previous: dict[str, Any] | None, raw_bid: Any, raw_ask: Any, timestamp: Any, digits: Any) -> dict[str, Any] | None:
    """Merge a broker spot event only when it contains a usable new quote side."""
    if previous is None:
        return None
    bid = decode_spot_price(raw_bid, digits)
    ask = decode_spot_price(raw_ask, digits)
    if bid is None and ask is None:
        return None
    updated = dict(previous)
    if bid is not None:
        updated["bid"] = bid
    if ask is not None:
        updated["ask"] = ask
    if timestamp is not None:
        updated["timestamp"] = int(timestamp)
    return updated

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
        ProtoOASymbolsForConversionReq,
        ProtoOASymbolsForConversionRes,
        ProtoOAAssetListReq,
        ProtoOAAssetListRes,
        ProtoOADealListReq,
        ProtoOADealListRes,
        ProtoOAReconcileReq,
        ProtoOAReconcileRes,
        ProtoOATraderReq,
        ProtoOATraderRes,
        ProtoOAGetPositionUnrealizedPnLReq,
        ProtoOAGetPositionUnrealizedPnLRes,
        ProtoOANewOrderReq,
        ProtoOAExecutionEvent,
        ProtoOAAmendPositionSLTPReq,
        ProtoOAClosePositionReq,
        ProtoOASubscribeSpotsReq,
        ProtoOASubscribeSpotsRes,
        ProtoOAUnsubscribeSpotsReq,
        ProtoOAUnsubscribeSpotsRes,
        ProtoOASpotEvent,
        ProtoOAErrorRes,
    )
    # Heartbeat is defined in the common messages module (not OpenApiMessages_pb2,
    # which has no such symbol). This is the same source the SDK's own
    # TcpProtocol uses for its automatic heartbeat.
    from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import (
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
    # Graceful degradation is intentional so unit tests can import this module
    # without the SDK, but the previous silent fallback masked a broken
    # deployment for weeks (every call died with
    # "AttributeError: 'NoneType' object has no attribute 'PROTOBUF_DEMO_HOST'").
    # Log the real failure loudly so a broken import is visible in deploy logs.
    import logging
    import traceback

    logging.getLogger("tradeguard.ctrader").error(
        "cTrader OpenAPI SDK import failed; broker integration is DISABLED "
        "(all cTrader routes will return 503 until fixed):\n%s",
        traceback.format_exc(),
    )
    Client = Protobuf = TcpProtocol = EndPoints = None
    reactor = None

@dataclass
class _Session:
    client: Any
    environment: str
    ready: bool = False
    waiters: dict[str, Future] = field(default_factory=dict)
    accounts: dict[int, str] = field(default_factory=dict)
    # NOTE: no manual protocol heartbeat here — the SDK's TcpProtocol sends
    # heartbeats automatically after 20s of idle time, and a manual
    # client.send(ProtoHeartbeatEvent()) would create a response deferred that
    # never resolves.
    spot_subscriptions: dict[tuple[int, int], str] = field(default_factory=dict)
    spot_subscription_refs: dict[tuple[int, int], int] = field(default_factory=dict)
    spot_waiters: dict[str, Future] = field(default_factory=dict)
    latest_spots: dict[tuple[int, int], dict[str, Any]] = field(default_factory=dict)
    symbol_digits: dict[tuple[int, int], int] = field(default_factory=dict)
    authorized_accounts: set[int] = field(default_factory=set)

class CTraderManager:
    def __init__(self):
        self._sessions: dict[str, _Session] = {}
        self._lock = threading.Lock()
        self._reactor_started = False
        self._reactor_thread: threading.Thread | None = None
        self._spot_callbacks: dict[str, set[Any]] = {}
        self._spot_lock = threading.Lock()
        # Serialize subscribe/unsubscribe transitions per broker account+symbol.
        # Without this, concurrent streams can duplicate broker requests and lose refs.
        self._spot_transition_locks: dict[tuple[str, int, int], asyncio.Lock] = {}

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
                session.spot_subscription_refs.clear()
                session.latest_spots.clear()
                session.symbol_digits.clear()
        # Any active mobile socket must stop showing stale broker data until
        # a fresh authenticated subscription is established.
        with self._spot_lock:
            callbacks = [callback for group in self._spot_callbacks.values() for callback in group]
        for callback in callbacks:
            try:
                callback({"type":"stream_error","provider":"ctrader","message":f"cTrader disconnected: {str(reason)[:120]}"})
            except Exception:
                pass
        self._fail_all(environment, f"cTrader disconnected: {reason}")

    def _fail_all(self, environment, reason):
        with self._lock:
            session = self._sessions.get(environment)
            waiters = []
            if session:
                # Fail and clear every outstanding request class on transport
                # loss; no caller should wait on a request from a dead session.
                waiters.extend(session.waiters.values())
                waiters.extend(session.spot_waiters.values())
                session.waiters.clear()
                session.spot_waiters.clear()
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
            # The account-list response is request-scoped data. Do not store it
            # in session.accounts, which is the account_id -> user_id heartbeat map.
            self._resolve(environment, getattr(message, "clientMsgId", ""), accounts)
            return
        if payload_type == ProtoOAAccountAuthRes().payloadType:
            data = Protobuf.extract(message)
            # Do not cache account authorization from an unsolicited response:
            # authorize_account validates the response against the requested ID
            # before it updates authorized_accounts.
            self._resolve(environment, getattr(message, "clientMsgId", ""), data)
            return
        if payload_type == ProtoOAErrorRes().payloadType:
            data = Protobuf.extract(message)
            error_code = str(getattr(data, "errorCode", "Unknown cTrader API error"))
            description = str(getattr(data, "description", "") or "")
            message_text = f"cTrader API error {error_code}: {description}".strip()
            client_msg_id = getattr(message, "clientMsgId", "")
            if not client_msg_id:
                client_msg_id = getattr(data, "clientMsgId", "")
            self._resolve(environment, client_msg_id, error=message_text)
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
                    key = (account_id, symbol_id)
                    digits = session.symbol_digits.get(key)
                    previous = session.latest_spots.get(key, {})
                    spot = dict(previous) if digits is not None else None
                    # cTrader spot prices use symbol-specific precision, not a
                    # universal divisor (JPY pairs and indices can differ).
                    if spot is not None:
                        spot = merge_spot_quote(
                            spot,
                            getattr(data, "bid", None),
                            getattr(data, "ask", None),
                            getattr(data, "timestamp", None),
                            digits,
                        )
                        if spot is not None:
                            session.latest_spots[key] = spot
            if user_id and spot:
                with self._spot_lock:
                    callbacks = tuple(self._spot_callbacks.get(user_id, ()))
                if callbacks:
                    bid = spot.get("bid")
                    ask = spot.get("ask")
                    payload = build_spot_tick_payload(account_id, symbol_id, spot)
                    for callback in callbacks:
                        try:
                            callback(payload)
                        except Exception:
                            # One disconnected mobile client must not block the
                            # other active subscribers for this user.
                            pass
            return
        if payload_type == ProtoOASubscribeSpotsRes().payloadType:
            self._resolve(environment, getattr(message, "clientMsgId", ""), Protobuf.extract(message))
            return
        if payload_type == ProtoOAUnsubscribeSpotsRes().payloadType:
            self._resolve(environment, getattr(message, "clientMsgId", ""), Protobuf.extract(message))
            return
        if payload_type == ProtoOAExecutionEvent().payloadType:
            data = Protobuf.extract(message)
            client_msg_id = getattr(message, "clientMsgId", "")
            execution_type = getattr(data, "executionType", None)
            partial_fill_type = getattr(ProtoOAExecutionType, "ORDER_PARTIAL_FILL", None)
            # Do not resolve an order waiter on ORDER_ACCEPTED or other
            # intermediate events: the caller could mistake an acknowledgement
            # for a fill. Return only fill evidence (full or partial) or an
            # explicit broker error. A partial fill must still be reconciled
            # by the caller before it can be treated as a completed order.
            is_fill = is_fill_execution(
                execution_type,
                filled_type=ProtoOAExecutionType.ORDER_FILLED,
                partial_fill_type=partial_fill_type,
            )
            if client_msg_id and (is_fill or getattr(data, "errorCode", "")):
                self._resolve(environment, client_msg_id, data)
            return
        # ClosePosition / AmendPositionSLTP results arrive as execution
        # events (handled above); the SDK defines no dedicated Res message
        # for them, so they are not (and never were) dispatched here.
        if payload_type in (ProtoOAReconcileRes().payloadType, ProtoOASymbolsListRes().payloadType, ProtoOASymbolsForConversionRes().payloadType, ProtoOAAssetListRes().payloadType, ProtoOADealListRes().payloadType):
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
        account_id = validate_positive_identifier(account_id, "account id")
        session = self._session(environment)
        with self._lock:
            if account_id in session.authorized_accounts:
                return {"ctidTraderAccountId":account_id,"authorized":True,"cached":True}
        req = ProtoOAAccountAuthReq()
        req.ctidTraderAccountId = account_id
        req.accessToken = access_token
        result = await self._send(environment, req)
        # Only cache authorization when the broker response explicitly binds
        # to the requested account. A successful transport response alone is
        # not sufficient evidence that this account was authorized.
        raw_authorized_account_id = (
            result.get("ctidTraderAccountId", result.get("account_id"))
            if isinstance(result, dict)
            else getattr(result, "ctidTraderAccountId", None)
        )
        try:
            authorized_account_id = validate_positive_identifier(
                raw_authorized_account_id, "authorized cTrader account id"
            )
        except ValueError as exc:
            raise RuntimeError("cTrader account authorization response did not confirm a valid account ID") from exc
        if authorized_account_id != account_id:
            raise RuntimeError("cTrader account authorization response does not match the requested account")
        with self._lock:
            session.authorized_accounts.add(account_id)
        return result

    def register_spot_callback(self, user_id: str, callback):
        """Register an independent market-stream listener for a user."""
        with self._spot_lock:
            self._spot_callbacks.setdefault(str(user_id), set()).add(callback)

    def unregister_spot_callback(self, user_id: str, callback=None):
        """Remove one listener without disconnecting other active mobile clients."""
        user_id = str(user_id)
        with self._spot_lock:
            current = self._spot_callbacks.get(user_id)
            if current is None:
                return
            if callback is None:
                self._spot_callbacks.pop(user_id, None)
                return
            current.discard(callback)
            if not current:
                self._spot_callbacks.pop(user_id, None)

    def _spot_transition_lock(self, environment: str, account_id: int, symbol_id: int) -> asyncio.Lock:
        key = ("live" if environment == "live" else "demo", int(account_id), int(symbol_id))
        with self._lock:
            return self._spot_transition_locks.setdefault(key, asyncio.Lock())

    async def subscribe_spots(self, user_id: str, account_id: int, symbol_id: int, access_token: str, environment="demo"):
        # Hold the transition lock through broker acknowledgement and local state
        # publication so concurrent streams cannot create duplicate subscriptions.
        lock = self._spot_transition_lock(environment, account_id, symbol_id)
        async with lock:
            return await self._subscribe_spots_once(
                user_id, account_id, symbol_id, access_token, environment
            )

    async def _subscribe_spots_once(self, user_id: str, account_id: int, symbol_id: int, access_token: str, environment="demo"):
        environment = "live" if environment == "live" else "demo"
        session = self._session(environment)
        account_id = validate_positive_identifier(account_id, "account id")
        symbol_id = validate_positive_identifier(symbol_id, "symbol id")
        key = (account_id, symbol_id)
        with self._lock:
            owner = session.spot_subscriptions.get(key)
            authorized = account_id in session.authorized_accounts
            if owner and owner != str(user_id):
                raise RuntimeError("Spot subscription key is already assigned to another user")
            if owner == str(user_id):
                # Multiple app screens share one broker subscription. Track
                # each stream so one disconnect cannot stop ticks for another.
                session.spot_subscription_refs[key] = session.spot_subscription_refs.get(key, 1) + 1
                return session.latest_spots.get(key)
        # The stream route authorizes once before subscribing to many symbols.
        # Re-authorize only when this connection has not yet authorized the account.
        if not authorized:
            await self.authorize_account(account_id, access_token, environment)
            with self._lock:
                authorized = account_id in session.authorized_accounts
            if not authorized:
                raise RuntimeError("cTrader account authorization was not confirmed")
        with self._lock:
            has_precision = key in session.symbol_digits
        if not has_precision:
            # Load the broker's symbol metadata before accepting scaled ticks.
            await self.symbols(account_id, environment)
            with self._lock:
                has_precision = key in session.symbol_digits
        if not has_precision:
            raise RuntimeError(f"cTrader precision metadata is unavailable for symbol {symbol_id}")
        req = ProtoOASubscribeSpotsReq()
        req.ctidTraderAccountId = int(account_id)
        req.symbolId.append(int(symbol_id))
        req.subscribeToSpotTimestamp = True
        await self._send(environment, req, timeout=20)
        with self._lock:
            session.spot_subscriptions[key] = str(user_id)
            session.spot_subscription_refs[key] = 1
        return session.latest_spots.get(key)

    async def unsubscribe_spots(self, user_id: str, account_id: int, symbol_id: int, environment="demo"):
        lock = self._spot_transition_lock(environment, account_id, symbol_id)
        async with lock:
            await self._unsubscribe_spots_once(user_id, account_id, symbol_id, environment)

    async def _unsubscribe_spots_once(self, user_id: str, account_id: int, symbol_id: int, environment="demo"):
        environment = "live" if environment == "live" else "demo"
        session = self._sessions.get(environment)
        if not session:
            return
        account_id = validate_positive_identifier(account_id, "account id")
        symbol_id = validate_positive_identifier(symbol_id, "symbol id")
        key = (account_id, symbol_id)
        with self._lock:
            if session.spot_subscriptions.get(key) != str(user_id):
                return
            refs = session.spot_subscription_refs.get(key, 1)
            if refs > 1:
                session.spot_subscription_refs[key] = refs - 1
                return
        req = ProtoOAUnsubscribeSpotsReq()
        req.ctidTraderAccountId = int(account_id)
        req.symbolId.append(int(symbol_id))
        await self._send(environment, req, timeout=15)
        with self._lock:
            # Remove routing only after the broker acknowledged unsubscribe.
            session.spot_subscriptions.pop(key, None)
            session.spot_subscription_refs.pop(key, None)
            session.latest_spots.pop(key, None)

    async def reconcile(self, account_id: int, environment="demo"):
        account_id = validate_positive_identifier(account_id, "account id")
        req = ProtoOAReconcileReq()
        req.ctidTraderAccountId = account_id
        return await self._send(environment, req)

    async def trader(self, account_id: int, environment="demo"):
        account_id = validate_positive_identifier(account_id, "account id")
        req = ProtoOATraderReq()
        req.ctidTraderAccountId = account_id
        return await self._send(environment, req)

    async def unrealized_pnl(self, account_id: int, environment="demo"):
        account_id = validate_positive_identifier(account_id, "account id")
        req = ProtoOAGetPositionUnrealizedPnLReq()
        req.ctidTraderAccountId = account_id
        return await self._send(environment, req)


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
                # A transport reconnect can restore application auth before any
                # account is reauthorized. Do not publish a healthy account
                # heartbeat until the selected account is authorized again.
                for account_id,user_id in session.accounts.items():
                    if account_id in session.authorized_accounts:
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


    async def assets(self, account_id: int, environment="demo"):
        """Return broker-provided asset metadata, including deposit currency."""
        account_id = validate_positive_identifier(account_id, "account id")
        req=ProtoOAAssetListReq()
        req.ctidTraderAccountId=account_id
        return await self._send(environment,req,timeout=20)

    async def deals(self, account_id: int, from_timestamp: int, to_timestamp: int, environment="demo", max_rows=1000):
        """Fetch broker deal history for a bounded time window."""
        account_id = validate_positive_identifier(account_id, "account id")
        from_timestamp, to_timestamp, max_rows = validate_deal_window(
            from_timestamp, to_timestamp, max_rows
        )
        req=ProtoOADealListReq()
        req.ctidTraderAccountId=account_id
        req.fromTimestamp=from_timestamp
        req.toTimestamp=to_timestamp
        req.maxRows=max_rows
        return await self._send(environment,req,timeout=25)

    async def symbols(self, account_id: int, environment="demo"):
        account_id = validate_positive_identifier(account_id, "account id")
        req=ProtoOASymbolsListReq()
        req.ctidTraderAccountId=account_id
        req.includeArchivedSymbols=False
        result = await self._send(environment,req,timeout=20)
        session = self._session(environment)
        with self._lock:
            for symbol in getattr(result, "symbol", []):
                symbol_id = getattr(symbol, "symbolId", None)
                digits = getattr(symbol, "digits", None)
                # Protobuf fields should already be integers; do not accept
                # malformed strings, booleans, or floats by coercing them.
                if (
                    isinstance(symbol_id, bool)
                    or not isinstance(symbol_id, int)
                    or symbol_id <= 0
                    or isinstance(digits, bool)
                    or not isinstance(digits, int)
                    or not 0 <= digits <= 12
                ):
                    continue
                session.symbol_digits[(account_id, symbol_id)] = digits
        return result

    async def symbols_for_conversion(self, account_id: int, first_asset_id: int, last_asset_id: int, environment="demo"):
        """Ask cTrader for the broker-defined asset conversion path.

        This returns path metadata only. It is not proof of an executable price,
        a deposit-currency loss estimate, or safe order sizing; callers must
        fetch current prices for the path and validate conversion direction.
        """
        account_id = validate_positive_identifier(account_id, "account id")
        first_asset_id = validate_positive_identifier(first_asset_id, "first asset id")
        last_asset_id = validate_positive_identifier(last_asset_id, "last asset id")
        if first_asset_id == last_asset_id:
            return {"account_id": account_id, "first_asset_id": first_asset_id,
                    "last_asset_id": last_asset_id, "symbols": [], "same_asset": True,
                    "risk_sizing_verified": False}
        req = ProtoOASymbolsForConversionReq()
        req.ctidTraderAccountId = account_id
        req.firstAssetId = first_asset_id
        req.lastAssetId = last_asset_id
        result = await self._send(environment, req, timeout=20)
        raw_symbols = []
        for item in getattr(result, "symbol", []):
            # Preserve protocol values for strict validation; never coerce a
            # malformed identifier into a seemingly valid broker instrument.
            raw_symbols.append({
                "symbol_id": getattr(item, "symbolId", None),
                "symbol_name": getattr(item, "symbolName", None),
                "base_asset_id": getattr(item, "baseAssetId", None),
                "quote_asset_id": getattr(item, "quoteAssetId", None),
            })
        try:
            symbols = normalize_conversion_symbols(raw_symbols)
        except ValueError as exc:
            raise RuntimeError(f"cTrader returned invalid asset-conversion metadata: {exc}") from exc
        return {"account_id": account_id, "first_asset_id": first_asset_id,
                "last_asset_id": last_asset_id, "symbols": symbols,
                "same_asset": False, "risk_sizing_verified": False}

    def conversion_quote_snapshot(self, account_id: int, conversion_symbols, environment="demo"):
        """Validate a fresh cached broker quote for every conversion-path symbol.

        This method does not create subscriptions or approve risk sizing. It
        only snapshots broker quotes already present in the cTrader stream
        cache, and fails closed if any required symbol lacks a fresh quote.
        """
        account_id = validate_positive_identifier(account_id, "account id")
        environment = "live" if environment == "live" else "demo"
        symbols = normalize_conversion_symbols(conversion_symbols)
        session = self._sessions.get(environment)
        if session is None:
            raise RuntimeError("cTrader quote stream is not initialized for this environment")
        with self._lock:
            if account_id not in session.authorized_accounts:
                raise RuntimeError("cTrader account authorization is required for conversion quotes")
            cached = {
                item["symbol_id"]: dict(session.latest_spots.get((account_id, item["symbol_id"]), {}))
                for item in symbols
            }
        now_ms = int(time.time() * 1000)
        try:
            quotes = quotes_from_spot_snapshot(
                symbols, cached, now_timestamp_ms=now_ms, max_quote_age_ms=5000,
            )
        except ValueError as exc:
            raise RuntimeError(f"cTrader conversion quote snapshot is not safe to use: {exc}") from exc
        return {
            "account_id": account_id,
            "environment": environment,
            "quotes_by_symbol_id": quotes,
            "snapshot_timestamp_ms": now_ms,
            "risk_sizing_verified": False,
        }

    async def subscribe_conversion_quotes(
        self, user_id: str, account_id: int, conversion_symbols, access_token: str,
        environment="demo", *, timeout: float = 20.0,
    ):
        """Subscribe to every broker conversion-path symbol and await fresh quotes.

        This establishes broker spot subscriptions before returning any quote
        snapshot. It fails closed on subscription errors, timeout, or stale
        quotes; it does not approve risk sizing or place an order.
        """
        account_id = validate_positive_identifier(account_id, "account id")
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("conversion quote timeout must be a positive finite number")
        symbols = normalize_conversion_symbols(conversion_symbols)
        environment = "live" if environment == "live" else "demo"

        # Subscribe every required symbol, not merely those with a cached quote.
        for symbol in symbols:
            await self.subscribe_spots(
                user_id, account_id, symbol["symbol_id"], access_token, environment
            )

        deadline = time.monotonic() + float(timeout)
        last_error = None
        while time.monotonic() < deadline:
            try:
                snapshot = self.conversion_quote_snapshot(account_id, symbols, environment)
                # Re-check freshness against a single current timestamp immediately
                # before returning; the snapshot helper is intentionally fail-closed.
                if len(snapshot.get("quotes_by_symbol_id", {})) != len(symbols):
                    raise RuntimeError("not every conversion symbol has a fresh quote")
                snapshot["subscriptions_confirmed"] = True
                return snapshot
            except RuntimeError as exc:
                last_error = exc
                await asyncio.sleep(min(0.1, max(0.0, deadline - time.monotonic())))

        detail = f": {last_error}" if last_error else ""
        raise RuntimeError(
            "Timed out waiting for fresh cTrader quotes for every conversion symbol; "
            "risk sizing must remain blocked" + detail
        )

    async def symbol_volume_units(self, account_id: int, symbol_id: int, environment="demo"):
        """Return raw cTrader volume constraints for future verified risk sizing.

        Raw protocol volumes are hundredths of a unit (100 = 1 unit on SDK
        instruments that express volume in units). This reports broker metadata
        only; callers must still convert target risk into volume using actual
        pip value and account-currency conversion before submitting an order.
        """
        account_id = validate_positive_identifier(account_id, "account id")
        symbol_id = validate_positive_identifier(symbol_id, "symbol id")
        symbols = await self.symbols(account_id, environment)
        symbol = next(
            (
                item for item in getattr(symbols, "symbol", [])
                if not isinstance(getattr(item, "symbolId", None), bool)
                and isinstance(getattr(item, "symbolId", None), int)
                and getattr(item, "symbolId", None) == symbol_id
            ),
            None,
        )
        if symbol is None:
            raise RuntimeError(f"cTrader symbol id {symbol_id} is not available")
        min_volume, max_volume, step_volume = validate_symbol_volume_metadata(
            getattr(symbol, "minVolume", None),
            getattr(symbol, "maxVolume", None),
            getattr(symbol, "stepVolume", None),
        )
        digits = getattr(symbol, "digits", None)
        lot_size = getattr(symbol, "lotSize", None)
        if isinstance(digits, bool) or not isinstance(digits, int) or not 0 <= digits <= 12:
            raise RuntimeError("cTrader symbol precision metadata is invalid")
        if isinstance(lot_size, bool) or not isinstance(lot_size, int) or lot_size <= 0:
            raise RuntimeError("cTrader symbol lot-size metadata is invalid")
        # Preserve broker asset identifiers when this SDK's symbol metadata
        # supplies them. Missing or malformed identifiers stay unavailable;
        # callers must not infer a contract type from a symbol's display name.
        base_asset_id = getattr(symbol, "baseAssetId", None)
        quote_asset_id = getattr(symbol, "quoteAssetId", None)
        if isinstance(base_asset_id, bool) or not isinstance(base_asset_id, int) or base_asset_id <= 0:
            base_asset_id = None
        if isinstance(quote_asset_id, bool) or not isinstance(quote_asset_id, int) or quote_asset_id <= 0:
            quote_asset_id = None
        return {
            "symbol_id": int(symbol_id),
            "symbol_name": str(getattr(symbol, "symbolName", "")),
            "digits": digits,
            "lot_size": lot_size,
            "base_asset_id": base_asset_id,
            "quote_asset_id": quote_asset_id,
            # cTrader's symbol metadata alone does not establish that a
            # product is a linear FX contract or prove its loss semantics.
            "instrument_type": None,
            "contract_model": None,
            "min_volume": min_volume,
            "max_volume": max_volume,
            "step_volume": step_volume,
            "volume_is_raw_protocol_units": True,
            "risk_sizing_verified": False,
        }

    async def new_market_order(self, account_id: int, symbol_id: int, side: str, volume: int, environment="demo"):
        account_id = validate_positive_identifier(account_id, "account id")
        symbol_id = validate_positive_identifier(symbol_id, "symbol id")
        volume = validate_protocol_volume(volume, field="order volume")
        if not isinstance(side, str) or side.upper() not in ("BUY", "SELL"):
            raise ValueError("cTrader order side must be BUY or SELL")
        req = ProtoOANewOrderReq()
        req.ctidTraderAccountId = account_id
        req.symbolId = symbol_id
        req.orderType = ProtoOAOrderType.MARKET
        req.tradeSide = ProtoOATradeSide.BUY if side.upper() == "BUY" else ProtoOATradeSide.SELL
        req.volume = volume
        return await self._send(environment, req, timeout=20)

    async def protect_position(self, account_id: int, position_id: int, stop_loss=None, take_profit=None, environment="demo"):
        account_id = validate_positive_identifier(account_id, "account id")
        position_id, stop_loss, take_profit = validate_protection_request(
            position_id, stop_loss=stop_loss, take_profit=take_profit
        )
        # cTrader uses absolute protection prices scaled to the symbol's digits.
        # Reject unsupported float/scaled values before they can reach the wire.
        session = self._session(environment)
        key_account = account_id
        if key_account not in session.authorized_accounts:
            raise RuntimeError("cTrader account authorization is required before amending position protection")
        req=ProtoOAAmendPositionSLTPReq()
        req.ctidTraderAccountId=account_id
        req.positionId=position_id
        if stop_loss is not None:
            req.stopLoss=stop_loss
        if take_profit is not None:
            req.takeProfit=take_profit
        return await self._send(environment,req,timeout=20)

    async def close_position(self, account_id: int, position_id: int, volume: int, environment="demo"):
        account_id = validate_positive_identifier(account_id, "account id")
        position_id = validate_positive_identifier(position_id, "position id")
        volume = validate_protocol_volume(volume, field="close volume")
        req = ProtoOAClosePositionReq()
        req.ctidTraderAccountId = account_id
        req.positionId = position_id
        req.volume = volume
        return await self._send(environment, req, timeout=20)

manager = CTraderManager()
