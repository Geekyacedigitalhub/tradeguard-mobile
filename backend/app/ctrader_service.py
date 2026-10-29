"""Cloud cTrader Open API connection manager.

Uses Spotware's official Python SDK. The SDK is asynchronous over Twisted, so the
reactor is isolated in a dedicated thread while FastAPI remains asyncio-native.
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
import uuid
from collections import deque
from concurrent.futures import Future
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
        ProtoOAAccountLogoutReq,
        ProtoOAAccountLogoutRes,
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
    # Per-request success evidence for execution events. Most requests confirm
    # via fill events; SL/TP amends confirm via ORDER_REPLACED. Empty means
    # "use the default fill-evidence rule" for that waiter.
    waiter_success_types: dict[str, tuple] = field(default_factory=dict)
    accounts: dict[int, str] = field(default_factory=dict)
    # NOTE: no manual protocol heartbeat here — the SDK's TcpProtocol sends
    # heartbeats automatically after 20s of idle time, and a manual
    # client.send(ProtoHeartbeatEvent()) would create a response deferred that
    # never resolves.
    # Consecutive broker response timeouts with no successful response since.
    # Two in a row means the session is "half-dead": the broker stopped
    # answering (e.g. after an access-token rotation revokes the session it
    # authorized) but left the TCP connection open, so Twisted's automatic
    # reconnect never triggers. A forced session reset is required.
    consecutive_timeouts: int = 0
    # Monotonic timestamp of the last forced reset for this environment slot;
    # rate-limits resets so a persistently failing broker cannot spawn a new
    # client every few seconds.
    reset_at: float = 0.0
    # Set when this session is replaced by _reset_session. Late callbacks or
    # messages from the old client must be ignored, never applied to the
    # replacement session.
    retired: bool = False
    # Set on a session created by _reset_session. The broker still holds the
    # previous (dead) channel's account login, so the first
    # authorize_account on this session must send an explicit
    # ProtoOAAccountLogoutReq before re-authorizing; otherwise the broker
    # rejects the auth with ALREADY_LOGGED_IN.
    logout_before_auth: bool = False
    spot_subscriptions: dict[tuple[int, int], str] = field(default_factory=dict)
    spot_subscription_refs: dict[tuple[int, int], int] = field(default_factory=dict)
    spot_waiters: dict[str, Future] = field(default_factory=dict)
    latest_spots: dict[tuple[int, int], dict[str, Any]] = field(default_factory=dict)
    symbol_digits: dict[tuple[int, int], int] = field(default_factory=dict)
    authorized_accounts: set[int] = field(default_factory=set)
    # Access token that each account authorization was made with. cTrader binds
    # an account authorization to the access token used, and tokens rotate
    # (fresh_access_token refreshes before expiry). A cached authorization made
    # with an old token must not suppress re-authorization with the new one,
    # or broker data calls fail until the transport happens to drop.
    authorized_tokens: dict[int, str] = field(default_factory=dict)

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
        # Lightweight operational state for /diag/status (read-only monitoring;
        # no broker calls). Keeps the last few distinct broker errors and the
        # last successful snapshot per environment.
        self._started_at = time.monotonic()
        self._status_lock = threading.Lock()
        self._recent_errors: deque[tuple[str, str, str]] = deque(maxlen=10)
        self._last_error_at: dict[str, float] = {}
        self.last_success_at: dict[str, str] = {}
        self.reset_count: dict[str, int] = {}

    def note_success(self, environment: str) -> None:
        environment = "live" if environment == "live" else "demo"
        with self._status_lock:
            self.last_success_at[environment] = datetime.now(timezone.utc).isoformat()

    def _note_error(self, environment: str, text: Any) -> None:
        environment = "live" if environment == "live" else "demo"
        now = time.monotonic()
        with self._status_lock:
            last = self._last_error_at.get(environment, 0.0)
            if last and now - last < 5.0:
                return  # dedupe: one recorded error per env per 5s
            self._last_error_at[environment] = now
            self._recent_errors.append(
                (datetime.now(timezone.utc).isoformat(), environment, str(text)[:200].replace("\n", " ")))

    def status(self) -> dict[str, Any]:
        with self._lock:
            sessions = {}
            for env, s in self._sessions.items():
                sessions[env] = {
                    "ready": s.ready,
                    "authorized_accounts": sorted(s.authorized_accounts),
                    "consecutive_timeouts": s.consecutive_timeouts,
                    "pending_requests": len(s.waiters),
                    "reset_age_s": round(time.monotonic() - s.reset_at, 1) if s.reset_at else None,
                    "logout_before_auth": s.logout_before_auth,
                }
        with self._status_lock:
            errors = list(self._recent_errors)
            success = dict(self.last_success_at)
            resets = dict(self.reset_count)
        return {
            "available": self.available(),
            "reactor_thread_alive": bool(self._reactor_thread is not None and self._reactor_thread.is_alive()),
            "uptime_s": round(time.monotonic() - self._started_at, 1),
            "reset_count": resets,
            "last_success_at": success,
            "recent_errors": errors,
            "sessions": sessions,
        }

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

    def _create_session(self, environment: str) -> tuple[Any, _Session]:
        host = EndPoints.PROTOBUF_LIVE_HOST if environment == "live" else EndPoints.PROTOBUF_DEMO_HOST
        client = Client(host, EndPoints.PROTOBUF_PORT, TcpProtocol)
        session = _Session(client=client, environment=environment)
        client.setConnectedCallback(lambda c: self._connected(environment, c))
        client.setDisconnectedCallback(lambda c, reason: self._disconnected(environment, c, reason))
        client.setMessageReceivedCallback(lambda c, msg: self._message(environment, c, msg))
        return client, session

    def _session(self, environment: str) -> _Session:
        environment = "live" if environment == "live" else "demo"
        self._ensure_reactor_alive()
        with self._lock:
            existing = self._sessions.get(environment)
            if existing:
                return existing
            client, session = self._create_session(environment)
            self._sessions[environment] = session
        reactor.callFromThread(client.startService)
        return session

    def _ensure_reactor_alive(self) -> None:
        """Start the Twisted reactor thread, or exit for a supervised restart.

        The Twisted reactor is a process-wide singleton that cannot be
        restarted once its thread dies. If the thread is gone, every cTrader
        send from now on would hang until the 15s request timeout, so the only
        clean recovery is a process restart (the platform restarts us).
        """
        if self._reactor_started and self._reactor_thread is not None and not self._reactor_thread.is_alive():
            logging.getLogger("tradeguard.ctrader").critical(
                "cTrader reactor thread died; exiting for supervised restart")
            os._exit(1)
        self.start()

    def _connected(self, environment, client):
        with self._lock:
            session = self._sessions.get(environment)
        if session is None or session.client is not client:
            return  # stale callback from a retired (replaced) session
        try:
            req = ProtoOAApplicationAuthReq()
            req.clientId = os.getenv("CTRADER_CLIENT_ID", "")
            req.clientSecret = os.getenv("CTRADER_CLIENT_SECRET", "")
            d = client.send(req)
            d.addErrback(lambda failure: self._fail_all(environment, str(failure)))
        except Exception:
            # A bug in the connect path must never escape into the Twisted
            # thread (it would kill the reactor thread for the whole process).
            logging.getLogger("tradeguard.ctrader").exception(
                "cTrader %s connect handler crashed; session stays unusable until reconnect", environment)

    def _disconnected(self, environment, client, reason):
        with self._lock:
            session = self._sessions.get(environment)
        if session is None or session.client is not client:
            return  # stale callback from a retired (replaced) session
        with self._lock:
            if session.ready:
                session.ready = False
                session.authorized_accounts.clear()
                session.authorized_tokens.clear()
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

    def _send_failed(self, session, environment, client_msg_id, failure):
        """Errback for a broker request that failed at the SDK layer.

        Twisted reports the SDK's 5-second response timeout as
        ``twisted.internet.defer.TimeoutError``. Two consecutive timeouts with
        no broker response in between means the session is half-dead and must
        be force-reset. The waiter is resolved against the session object it
        was registered on (not an environment lookup) because a concurrent
        reset may have replaced the session in the dict by now.
        """
        value = getattr(failure, "value", None)
        if isinstance(value, BaseException) and type(value).__name__ == "TimeoutError":
            self._note_broker_timeout(environment)
        self._note_error(environment, failure)
        with self._lock:
            future = session.waiters.pop(client_msg_id, None)
            session.waiter_success_types.pop(client_msg_id, None)
        if future is not None and not future.done():
            future.set_exception(RuntimeError(str(failure)))

    def _note_broker_success(self, environment):
        with self._lock:
            session = self._sessions.get(environment)
            if session is not None and getattr(session, "consecutive_timeouts", 0):
                session.consecutive_timeouts = 0

    def _note_broker_timeout(self, environment):
        environment = "live" if environment == "live" else "demo"
        should_reset = False
        with self._lock:
            session = self._sessions.get(environment)
            if session is None:
                return
            session.consecutive_timeouts += 1
            now = time.monotonic()
            if session.consecutive_timeouts >= 2 and (now - session.reset_at) > 20.0:
                session.reset_at = now
                should_reset = True
        if should_reset:
            logging.getLogger("tradeguard.ctrader").warning(
                "cTrader %s broker stopped responding (2+ consecutive response timeouts); forcing session reset",
                environment)
            self._reset_session(environment)

    def _reset_session(self, environment):
        """Replace a half-dead broker session with a fresh client + connection.

        A forced stop of the old client guarantees a local TCP close, so a
        zombie connection (broker silent but TCP open) cannot survive the
        reset. The replacement goes through the normal connect path: app auth,
        then account re-authorization with the current access token.
        """
        environment = "live" if environment == "live" else "demo"
        self._ensure_reactor_alive()
        with self._status_lock:
            self.reset_count[environment] = self.reset_count.get(environment, 0) + 1
        new_client, new_session = self._create_session(environment)
        old_session = None
        with self._lock:
            old_session = self._sessions.get(environment)
            if old_session is not None:
                old_session.retired = True
                # Inherit the reset cooldown: an immediately unstable
                # replacement must not trigger back-to-back resets.
                new_session.reset_at = max(old_session.reset_at, new_session.reset_at)
            else:
                new_session.reset_at = time.monotonic()
            # The previous channel's account login may still be registered on
            # the broker side (its TCP close never arrived there). Make the
            # first authorization on this session send an explicit account
            # logout first (see logout_before_auth in authorize_account).
            if old_session is not None:
                new_session.logout_before_auth = True
            self._sessions[environment] = new_session
        if old_session is not None:
            self._fail_session(old_session, "cTrader session reset (broker stopped responding)")

            def _swap(old=old_session, new=new_client):
                # Stop the old channel FIRST and give the broker a moment to
                # release the account login before the replacement channel
                # re-authorizes the same account. Otherwise the new channel's
                # authorization can be rejected with ALREADY_LOGGED_IN while
                # the previous (dead) channel is still registered on the
                # broker side.
                try:
                    # Best effort: force a TCP RST (not a graceful FIN) when
                    # the old socket closes. A zombie connection may swallow
                    # a FIN on the broker side; a RST forces the broker's TCP
                    # stack to tear the channel down, which releases the
                    # account login.
                    import socket as _socket
                    import struct as _struct
                    _factory = getattr(old.client, "factory", None)
                    _noisy = getattr(_factory, "noisyProtocol", None) if _factory is not None else None
                    _transport = getattr(_noisy, "transport", None) if _noisy is not None else None
                    _raw_sock = getattr(_transport, "sock", None) if _transport is not None else None
                    if _raw_sock is not None:
                        _raw_sock.setsockopt(
                            _socket.SOL_SOCKET, _socket.SO_LINGER, _struct.pack("ii", 1, 0))
                except Exception:
                    pass
                try:
                    # Stop the base Twisted service directly: the SDK's
                    # override refuses to stop a client it does not think is
                    # connected, which is exactly the zombie case.
                    from twisted.application.internet import ClientService as _ClientService
                    _ClientService.stopService(old.client)
                except Exception:
                    pass
                try:
                    from twisted.internet import reactor as _twisted_reactor
                    _twisted_reactor.callLater(2.0, new.startService)
                except Exception:
                    new.startService()

            try:
                reactor.callFromThread(_swap)
            except Exception:
                reactor.callFromThread(lambda client=new_client: client.startService())
        else:
            reactor.callFromThread(lambda client=new_client: client.startService())

    def _fail_session(self, session, reason):
        with self._lock:
            waiters = list(session.waiters.values()) + list(session.spot_waiters.values())
            session.waiters.clear()
            session.spot_waiters.clear()
        for future in waiters:
            if not future.done():
                future.set_exception(RuntimeError(reason))

    def _message(self, environment, client, message):
        """Reactor-thread entry point for every broker message.

        A bug in message handling must never escape into the Twisted thread:
        that would kill the reactor thread and every cTrader request in the
        process. Drop the message and keep the session usable.
        """
        with self._lock:
            session = self._sessions.get(environment)
        if session is None or session.client is not client:
            return  # stale message from a retired (replaced) session
        try:
            self._note_broker_success(environment)
            self._dispatch_message(environment, client, message)
        except Exception:
            logging.getLogger("tradeguard.ctrader").exception(
                "dropping cTrader message on %s; session continues", environment)

    def _dispatch_message(self, environment, client, message):
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
        if payload_type == ProtoOAAccountLogoutRes().payloadType:
            # Explicit account logout confirmation (ProtoOAAccountLogoutReq
            # sent by logout_account / post-reset authorize_account).
            self._resolve(environment, getattr(message, "clientMsgId", ""), Protobuf.extract(message))
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
            # An execution event carrying a non-zero errorCode is a broker
            # rejection: surface it as an error, never as a successful result.
            error_code = getattr(data, "errorCode", 0) or 0
            if client_msg_id and error_code:
                self._resolve(environment, client_msg_id, error=f"cTrader execution error {error_code}")
                return
            # Success evidence differs by request type: new orders and closes
            # confirm via fill events; SL/TP amends confirm via ORDER_REPLACED
            # (there is no dedicated Res message for amend requests). A waiter
            # registered with an explicit success set uses it; every other
            # waiter keeps the fill-evidence rule. Never resolve on
            # ORDER_ACCEPTED or other intermediate events, and a partial fill
            # must still be reconciled by the caller before it can be treated
            # as a completed order.
            with self._lock:
                session = self._sessions.get(environment)
                success_types = session.waiter_success_types.get(client_msg_id) if session else None
            if success_types:
                is_success = execution_type in success_types
            else:
                partial_fill_type = getattr(ProtoOAExecutionType, "ORDER_PARTIAL_FILL", None)
                is_success = is_fill_execution(
                    execution_type,
                    filled_type=ProtoOAExecutionType.ORDER_FILLED,
                    partial_fill_type=partial_fill_type,
                )
            if client_msg_id and is_success:
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

    async def _send(self, environment: str, request, timeout: float = 15, success_execution_types=None):
        self._ensure_reactor_alive()
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
            if success_execution_types:
                session.waiter_success_types[client_msg_id] = tuple(success_execution_types)
        def send():
            d = session.client.send(request, clientMsgId=client_msg_id)
            d.addErrback(lambda failure: self._send_failed(session, environment, client_msg_id, failure))
        reactor.callFromThread(send)
        try:
            return await asyncio.wait_for(asyncio.wrap_future(future), timeout=timeout)
        except asyncio.TimeoutError:
            # The SDK's own 5s response timeout normally fails the request
            # first; reaching this means the send/timeout machinery itself is
            # stuck (reactor wedged). Count it the same way and, if needed,
            # the reset path (or the dead-reactor exit) takes over.
            self._note_broker_timeout(environment)
            raise RuntimeError(
                f"cTrader {environment} request timed out after {timeout:.0f}s; broker session is resetting")
        finally:
            with self._lock:
                session = self._sessions.get(environment)
                if session:
                    session.waiters.pop(client_msg_id, None)
                    session.waiter_success_types.pop(client_msg_id, None)
                    # Expire waiters that timed out or were cancelled. The
                    # response may arrive later, but must not leak a Future.
                    for key, waiter in list(session.waiters.items()):
                        if waiter.done():
                            session.waiters.pop(key, None)
                            session.waiter_success_types.pop(key, None)

    async def list_accounts(self, access_token: str, environment="demo"):
        req = ProtoOAGetAccountListByAccessTokenReq()
        req.accessToken = access_token
        result = await self._send(environment, req)
        if isinstance(result, dict):
            error_code = result.get("errorCode") or result.get("error_code")
            if error_code:
                raise RuntimeError(f"cTrader account list error: {error_code}")
        return result

    async def logout_account(self, account_id: int, environment="demo"):
        """Explicitly log the account out (ProtoOAAccountLogoutReq).

        Releases the account from every broker channel, including a previous
        dead channel whose TCP close never reached the broker. Callers treat
        this call as best effort: if the account is not logged in anywhere
        the broker answers with an error, which they ignore.
        """
        environment = "live" if environment == "live" else "demo"
        account_id = validate_positive_identifier(account_id, "account id")
        req = ProtoOAAccountLogoutReq()
        req.ctidTraderAccountId = account_id
        return await self._send(environment, req, timeout=8)

    async def authorize_account(self, account_id: int, access_token: str, environment="demo"):
        environment = "live" if environment == "live" else "demo"
        account_id = validate_positive_identifier(account_id, "account id")
        session = self._session(environment)
        with self._lock:
            # Reuse the cached authorization only when it was made with the
            # SAME access token; a rotated token requires a fresh
            # ProtoOAAccountAuthReq so the broker session is bound to a
            # token that is still valid.
            if account_id in session.authorized_accounts and session.authorized_tokens.get(account_id) == access_token:
                return {"ctidTraderAccountId":account_id,"authorized":True,"cached":True}
        with self._lock:
            do_logout = session.logout_before_auth
        if do_logout:
            # This session replaced a dead one: the broker may still hold the
            # account login from the previous channel (its TCP close never
            # arrived there). Release it explicitly before re-authorizing;
            # otherwise the broker rejects the auth with ALREADY_LOGGED_IN.
            # Best effort: an account that is not logged in anywhere simply
            # yields an error response, which we ignore.
            try:
                await self.logout_account(account_id, environment)
            except Exception:
                pass
            with self._lock:
                session.logout_before_auth = False
        req = ProtoOAAccountAuthReq()
        req.ctidTraderAccountId = account_id
        req.accessToken = access_token
        try:
            result = await self._send(environment, req)
        except Exception as exc:
            # "Already logged in" is a SUCCESS condition, not a failure: the
            # broker confirms this account is authorized on this channel. It
            # shows up right after a forced session reset, when the previous
            # (dead) channel's login has not fully released on the broker
            # side yet. Caching and moving on keeps the snapshot flow moving;
            # a later token rotation still forces a fresh attempt because the
            # cached token will not match.
            if "ALREADY_LOGGED_IN" in str(exc):
                with self._lock:
                    session.authorized_accounts.add(account_id)
                    session.authorized_tokens[account_id] = access_token
                    # The broker is still settling the previous channel's
                    # login; avoid an immediate follow-up reset storm.
                    session.reset_at = time.monotonic()
                return {"ctidTraderAccountId":account_id,"authorized":True,"already_authorized":True}
            # The broker rejected this authorization (or the transport failed):
            # drop any cached authorization so the next call retries from a
            # clean state instead of trusting stale broker state.
            with self._lock:
                session.authorized_accounts.discard(account_id)
                session.authorized_tokens.pop(account_id, None)
            raise
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
            session.authorized_tokens[account_id] = access_token
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

    async def relogin_account(self, account_id: int, access_token: str, environment="demo"):
        """Full account re-login on the CURRENT channel: explicit logout,
        brief pause, fresh authorization.

        Used when the broker authenticates the account but serves empty
        account data — the broker-side session state for this account is
        wedged, and neither a plain re-authorize nor a brand-new channel can
        clear it (a logout sent on another channel does not reach the login
        registered on this one).
        """
        environment = "live" if environment == "live" else "demo"
        account_id = validate_positive_identifier(account_id, "account id")
        session = self._session(environment)
        with self._lock:
            session.authorized_accounts.discard(account_id)
            session.authorized_tokens.pop(account_id, None)
        try:
            await self.logout_account(account_id, environment)
        except Exception:
            pass  # best effort: the account may not be logged in on this channel
        await asyncio.sleep(1.0)  # give the broker a beat to release the session
        return await self.authorize_account(account_id, access_token, environment)

    async def trader_verified(self, account_id: int, access_token: str, environment="demo"):
        """trader() that guarantees a populated trader payload.

        If the broker serves an empty trader response (auth OK, data
        missing — a wedged broker-side account session), performs one full
        re-login on the current channel and retries. Raises RuntimeError
        with an actionable cause if data is still missing.
        """
        response = await self.trader(account_id, environment)
        if getattr(response, "trader", None) is not None:
            return response
        logging.getLogger("tradeguard.ctrader").warning(
            "cTrader %s account=%s returned empty trader data; attempting full re-login on current channel",
            environment, account_id)
        self._note_error(environment, "empty trader response; re-login attempt started")
        await self.relogin_account(account_id, access_token, environment)
        response = await self.trader(account_id, environment)
        if getattr(response, "trader", None) is not None:
            logging.getLogger("tradeguard.ctrader").info(
                "cTrader %s account=%s re-login recovered trader data", environment, account_id)
            return response
        raise RuntimeError(
            f"cTrader {environment} returned no trader data for account {account_id} "
            "even after a full re-login; the account may be inactive, expired, or "
            "restricted on the broker side — verify it in the cTrader web terminal")


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
        # cTrader confirms an SL/TP amendment with an ORDER_REPLACED execution
        # event, not a fill event. Register it as the success evidence for
        # this request so a successful protect does not time out after 20s
        # while a rejection (non-zero errorCode) still fails fast as an error.
        replace_type = getattr(ProtoOAExecutionType, "ORDER_REPLACED", None)
        success_types = (replace_type,) if replace_type is not None else None
        return await self._send(environment, req, timeout=20, success_execution_types=success_types)

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
