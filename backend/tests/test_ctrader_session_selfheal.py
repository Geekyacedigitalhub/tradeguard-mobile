"""Regression tests: cTrader half-dead session detection and forced reset.

A "half-dead" session is one where the broker stopped answering requests
(e.g. an access-token rotation revoked the session it authorized) but left
the TCP connection open. Twisted's automatic reconnect only fires on real
TCP disconnects, so without this logic every request would hit the SDK's
5s response timeout forever and the mobile app would stay STALE until a
process restart.

Covered behavior:
- one timeout is recorded, no reset;
- two consecutive timeouts force a session reset (fresh client, old session
  retired, old waiters failed, cooldown inherited);
- any received message clears the timeout counter;
- resets are rate-limited to at most one per 60s per environment;
- messages/disconnects from a retired (replaced) client are ignored;
- a dispatcher bug never propagates into the Twisted thread;
- a dead reactor thread exits the process for a supervised restart;
- ALREADY_LOGGED_IN after a reset is treated as a successful authorization
  (the broker still holds the dead channel's login while it releases);
- a replacement session sends an explicit ProtoOAAccountLogoutReq before its
  first account authorization (releases the dead channel's login on the
  broker side), and a logout failure never blocks the authorization.
"""
import asyncio
import unittest
from types import SimpleNamespace
from unittest import mock

from app.ctrader_service import CTraderManager, ProtoOAApplicationAuthRes, _Session
import app.ctrader_service as service_module


def make_session(environment="demo", client=None, ready=True, **extra):
    session = _Session(
        client=client if client is not None else object(),
        environment=environment,
        ready=ready,
    )
    for name, value in extra.items():
        setattr(session, name, value)
    return session


class TimeoutCounterTests(unittest.TestCase):
    def setUp(self):
        self.manager = CTraderManager()

    def test_single_timeout_is_recorded_without_reset(self):
        session = make_session()
        self.manager._sessions["demo"] = session
        self.manager._note_broker_timeout("demo")
        self.assertEqual(session.consecutive_timeouts, 1)
        with self.manager._lock:
            self.assertIs(self.manager._sessions["demo"], session)

    def test_success_clears_the_timeout_counter(self):
        session = make_session()
        self.manager._sessions["demo"] = session
        self.manager._note_broker_timeout("demo")
        self.assertEqual(session.consecutive_timeouts, 1)
        self.manager._note_broker_success("demo")
        self.assertEqual(session.consecutive_timeouts, 0)
        # A single later timeout must not reset (counter restarted).
        self.manager._note_broker_timeout("demo")
        with self.manager._lock:
            self.assertIs(self.manager._sessions["demo"], session)

    def test_two_consecutive_timeouts_force_a_reset(self):
        old = make_session()
        self.manager._sessions["demo"] = old
        loop = asyncio.new_event_loop()
        future = loop.create_future()
        old.waiters["msg-1"] = future

        new_client = object()
        new_session = make_session(client=new_client)
        with mock.patch.object(self.manager, "_create_session",
                               return_value=(new_client, new_session)) as create, \
             mock.patch.object(self.manager, "_ensure_reactor_alive"):
            self.manager._note_broker_timeout("demo")
            self.manager._note_broker_timeout("demo")

        self.assertEqual(create.call_count, 1)
        self.assertTrue(old.retired)
        with self.manager._lock:
            self.assertIs(self.manager._sessions["demo"], new_session)
        self.assertEqual(new_session.consecutive_timeouts, 0)
        # The cooldown is inherited from the retired session.
        self.assertGreater(new_session.reset_at, 0.0)
        self.assertTrue(future.done())
        self.assertIn("reset", str(future.exception()))
        loop.close()

    def test_resets_are_rate_limited_within_cooldown(self):
        old = make_session()
        self.manager._sessions["demo"] = old
        new_client = object()
        new_session = make_session(client=new_client)
        with mock.patch.object(self.manager, "_create_session",
                               return_value=(new_client, new_session)) as create, \
             mock.patch.object(self.manager, "_ensure_reactor_alive"):
            self.manager._note_broker_timeout("demo")
            self.manager._note_broker_timeout("demo")  # -> first reset
            # The replacement times out twice immediately: the inherited
            # cooldown must prevent a second reset.
            self.manager._note_broker_timeout("demo")
            self.manager._note_broker_timeout("demo")
            self.assertEqual(create.call_count, 1)
            with self.manager._lock:
                self.assertIs(self.manager._sessions["demo"], new_session)


class StaleCallbackTests(unittest.TestCase):
    """Events from a replaced client must never touch the new session."""

    def setUp(self):
        self.manager = CTraderManager()

    def test_message_from_retired_client_is_ignored(self):
        old = make_session()
        old.retired = True
        new_session = make_session(ready=False)
        self.manager._sessions["demo"] = new_session
        # A late app-auth response arriving from the OLD client must not
        # mark the NEW session ready. (clientMsgId is attached to received
        # messages by the SDK protocol layer, not by the message class.)
        message = ProtoOAApplicationAuthRes()
        self.manager._message("demo", old.client, message)
        self.assertFalse(new_session.ready)

    def test_message_from_current_client_marks_ready(self):
        session = make_session(ready=False)
        self.manager._sessions["demo"] = session
        message = ProtoOAApplicationAuthRes()
        self.manager._message("demo", session.client, message)
        self.assertTrue(session.ready)

    def test_disconnect_from_retired_client_is_ignored(self):
        old = make_session()
        old.retired = True
        new_session = make_session(ready=True, authorized_tokens={42: "tok"})
        self.manager._sessions["demo"] = new_session
        self.manager._disconnected("demo", old.client, "zombie close")
        self.assertTrue(new_session.ready)
        self.assertEqual(new_session.authorized_tokens, {42: "tok"})

    def test_disconnect_from_current_client_clears_state(self):
        session = make_session(ready=True, authorized_tokens={42: "tok"})
        self.manager._sessions["demo"] = session
        self.manager._disconnected("demo", session.client, "real close")
        self.assertFalse(session.ready)
        self.assertEqual(session.authorized_tokens, {})


class DispatcherSafetyTests(unittest.TestCase):
    """A bug in message handling must never escape into the Twisted thread."""

    def setUp(self):
        self.manager = CTraderManager()

    def test_dispatcher_exception_is_swallowed(self):
        session = make_session()
        self.manager._sessions["demo"] = session

        class BoomProtobuf:
            @staticmethod
            def extract(message):
                raise RuntimeError("boom")

        # An account-list-shaped message reaches Protobuf.extract.
        message = service_module.ProtoOAGetAccountListByAccessTokenRes()
        with mock.patch.object(service_module, "Protobuf", BoomProtobuf):
            self.manager._message("demo", session.client, message)  # must not raise
        self.assertTrue(session.ready)  # session stays usable

    def test_send_failed_counts_timeout_and_resolves_waiter(self):
        from twisted.internet import defer as tdefer

        session = make_session()
        self.manager._sessions["demo"] = session
        loop = asyncio.new_event_loop()
        future = loop.create_future()
        session.waiters["m1"] = future

        self.manager._send_failed(session, "demo", "m1", tdefer.Failure(tdefer.TimeoutError()))
        self.assertEqual(session.consecutive_timeouts, 1)
        self.assertTrue(future.done())
        self.assertIn("TimeoutError", str(future.exception()))
        self.assertNotIn("m1", session.waiters)
        loop.close()

    def test_send_failed_non_timeout_failure_does_not_count(self):
        from twisted.internet import defer as tdefer

        session = make_session()
        self.manager._sessions["demo"] = session
        loop = asyncio.new_event_loop()
        future = loop.create_future()
        session.waiters["m2"] = future

        self.manager._send_failed(session, "demo", "m2", tdefer.Failure(RuntimeError("other")))
        self.assertEqual(session.consecutive_timeouts, 0)
        self.assertTrue(future.done())
        self.assertIn("other", str(future.exception()))
        loop.close()


class AlreadyLoggedInTests(unittest.TestCase):
    """After a forced reset, the broker can still hold the previous (dead)
    channel's account login and answer the re-authorization with
    ALREADY_LOGGED_IN. That is a success condition: the account IS authorized
    on this channel, so cache it and let the snapshot flow continue."""

    def setUp(self):
        self.manager = CTraderManager()

    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_already_logged_in_is_treated_as_success(self):
        session = make_session()
        self.manager._sessions["demo"] = session

        async def fake_send(environment, request, timeout=15, success_execution_types=None):
            raise RuntimeError(
                "cTrader API error ALREADY_LOGGED_IN: "
                "Trading account is already authorized in this channel")

        with mock.patch.object(self.manager, "_send", side_effect=fake_send):
            result = self._run(self.manager.authorize_account(42, "tok-1", "demo"))

        self.assertTrue(result["authorized"])
        self.assertEqual(result["ctidTraderAccountId"], 42)
        self.assertIn(42, session.authorized_accounts)
        self.assertEqual(session.authorized_tokens.get(42), "tok-1")

    def test_cached_authorization_with_same_token_skips_broker(self):
        session = make_session()
        session.authorized_accounts.add(42)
        session.authorized_tokens[42] = "tok-1"
        self.manager._sessions["demo"] = session
        with mock.patch.object(self.manager, "_send") as send:
            result = self._run(self.manager.authorize_account(42, "tok-1", "demo"))
        self.assertTrue(result["cached"])
        send.assert_not_called()

    def test_other_authorization_errors_still_raise_and_clear_cache(self):
        session = make_session()
        session.authorized_accounts.add(42)
        session.authorized_tokens[42] = "tok-old"
        self.manager._sessions["demo"] = session

        async def fake_send(environment, request, timeout=15, success_execution_types=None):
            raise RuntimeError("cTrader API error FORBIDDEN: access token expired")

        with mock.patch.object(self.manager, "_send", side_effect=fake_send):
            with self.assertRaises(RuntimeError):
                self._run(self.manager.authorize_account(42, "tok-new", "demo"))
        self.assertNotIn(42, session.authorized_accounts)
        self.assertNotIn(42, session.authorized_tokens)


class AccountLogoutTests(unittest.TestCase):
    """After a forced reset the broker still holds the dead channel's account
    login. The replacement session must release it with an explicit
    ProtoOAAccountLogoutReq before re-authorizing, instead of hitting
    ALREADY_LOGGED_IN."""

    def setUp(self):
        self.manager = CTraderManager()

    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_reset_flags_logout_before_auth_on_replacement(self):
        old = make_session()
        self.manager._sessions["demo"] = old
        new_client = object()
        new_session = make_session(client=new_client)
        with mock.patch.object(self.manager, "_create_session",
                               return_value=(new_client, new_session)), \
             mock.patch.object(self.manager, "_ensure_reactor_alive"):
            self.manager._note_broker_timeout("demo")
            self.manager._note_broker_timeout("demo")
        self.assertIs(self.manager._sessions["demo"], new_session)
        self.assertTrue(new_session.logout_before_auth)
        self.assertFalse(old.logout_before_auth)

    def test_authorize_sends_logout_first_when_flagged(self):
        session = make_session()
        session.logout_before_auth = True
        self.manager._sessions["demo"] = session
        calls = []

        async def fake_send(environment, request, timeout=15, success_execution_types=None):
            calls.append(type(request).__name__)
            return {"ctidTraderAccountId": 42, "authorized": True}

        with mock.patch.object(self.manager, "_send", side_effect=fake_send):
            result = self._run(self.manager.authorize_account(42, "tok-1", "demo"))

        self.assertEqual(calls, ["ProtoOAAccountLogoutReq", "ProtoOAAccountAuthReq"])
        self.assertTrue(result["authorized"])
        self.assertFalse(session.logout_before_auth)
        self.assertIn(42, session.authorized_accounts)

    def test_logout_failure_does_not_block_authorization(self):
        session = make_session()
        session.logout_before_auth = True
        self.manager._sessions["demo"] = session
        calls = []

        async def fake_send(environment, request, timeout=15, success_execution_types=None):
            calls.append(type(request).__name__)
            if type(request).__name__ == "ProtoOAAccountLogoutReq":
                raise RuntimeError("cTrader API error NOT_LOGGED_IN: no such session")
            return {"ctidTraderAccountId": 42, "authorized": True}

        with mock.patch.object(self.manager, "_send", side_effect=fake_send):
            result = self._run(self.manager.authorize_account(42, "tok-1", "demo"))

        self.assertEqual(calls, ["ProtoOAAccountLogoutReq", "ProtoOAAccountAuthReq"])
        self.assertTrue(result["authorized"])
        self.assertFalse(session.logout_before_auth)

    def test_logout_account_sends_account_logout_request(self):
        session = make_session()
        self.manager._sessions["demo"] = session
        captured = {}

        async def fake_send(environment, request, timeout=15, success_execution_types=None):
            captured["type"] = type(request).__name__
            captured["account"] = request.ctidTraderAccountId
            captured["timeout"] = timeout
            return {"ctidTraderAccountId": 42}

        with mock.patch.object(self.manager, "_send", side_effect=fake_send):
            self._run(self.manager.logout_account(42, "demo"))

        self.assertEqual(captured["type"], "ProtoOAAccountLogoutReq")
        self.assertEqual(captured["account"], 42)
        self.assertEqual(captured["timeout"], 8)


async def _async_noop(*args, **kwargs):
    return None


class ReloginTests(unittest.TestCase):
    """Empty broker data (auth OK, payload missing) must trigger a full
    channel re-login, and still-empty data must surface an actionable error
    instead of a silent STALE state."""

    def setUp(self):
        self.manager = CTraderManager()

    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_trader_verified_returns_populated_response_directly(self):
        session = make_session()
        self.manager._sessions["demo"] = session
        populated = SimpleNamespace(trader=SimpleNamespace(traderLogin=1))

        async def fake_send(environment, request, timeout=15, success_execution_types=None):
            return populated

        with mock.patch.object(self.manager, "_send", side_effect=fake_send):
            result = self._run(self.manager.trader_verified(42, "tok-1", "demo"))
        self.assertIs(result, populated)

    def test_trader_verified_relogs_on_empty_then_succeeds(self):
        session = make_session()
        self.manager._sessions["demo"] = session
        calls = {"trader": 0, "logout": 0, "auth": 0}
        populated = SimpleNamespace(trader=SimpleNamespace(traderLogin=1))

        async def fake_send(environment, request, timeout=15, success_execution_types=None):
            name = type(request).__name__
            if name == "ProtoOATraderReq":
                calls["trader"] += 1
                return SimpleNamespace(trader=None) if calls["trader"] == 1 else populated
            if name == "ProtoOAAccountLogoutReq":
                calls["logout"] += 1
                return {"ctidTraderAccountId": 42}
            if name == "ProtoOAAccountAuthReq":
                calls["auth"] += 1
                return {"ctidTraderAccountId": 42}
            return {}

        with mock.patch.object(self.manager, "_send", side_effect=fake_send), \
             mock.patch("asyncio.sleep", new=_async_noop):
            result = self._run(self.manager.trader_verified(42, "tok-1", "demo"))

        self.assertIs(result, populated)
        self.assertEqual(calls, {"trader": 2, "logout": 1, "auth": 1})

    def test_trader_verified_raises_actionable_error_when_still_empty(self):
        session = make_session()
        self.manager._sessions["demo"] = session

        async def fake_send(environment, request, timeout=15, success_execution_types=None):
            name = type(request).__name__
            if name == "ProtoOATraderReq":
                return SimpleNamespace(trader=None)
            if name == "ProtoOAAccountLogoutReq":
                return {"ctidTraderAccountId": 42}
            return {"ctidTraderAccountId": 42}

        with mock.patch.object(self.manager, "_send", side_effect=fake_send), \
             mock.patch("asyncio.sleep", new=_async_noop):
            with self.assertRaisesRegex(RuntimeError, "web terminal"):
                self._run(self.manager.trader_verified(42, "tok-1", "demo"))

    def test_relogin_clears_cache_and_orders_logout_before_auth(self):
        session = make_session()
        session.authorized_accounts.add(42)
        session.authorized_tokens[42] = "tok-old"
        self.manager._sessions["demo"] = session
        order = []

        async def fake_send(environment, request, timeout=15, success_execution_types=None):
            order.append(type(request).__name__)
            if type(request).__name__ == "ProtoOAAccountLogoutReq":
                raise RuntimeError("cTrader API error NOT_LOGGED_IN: no such session")
            return {"ctidTraderAccountId": 42}

        with mock.patch.object(self.manager, "_send", side_effect=fake_send), \
             mock.patch("asyncio.sleep", new=_async_noop):
            self._run(self.manager.relogin_account(42, "tok-new", "demo"))

        self.assertEqual(order, ["ProtoOAAccountLogoutReq", "ProtoOAAccountAuthReq"])
        self.assertEqual(session.authorized_tokens.get(42), "tok-new")


class StatusReportingTests(unittest.TestCase):
    """/diag/status backend: error dedupe, success timestamps, reset counts."""

    def setUp(self):
        self.manager = CTraderManager()

    def test_status_reports_sessions_and_counters(self):
        session = make_session()
        session.consecutive_timeouts = 2
        self.manager._sessions["demo"] = session
        self.manager.reset_count["demo"] = 1
        self.manager.note_success("demo")
        self.manager._note_error("demo", "cTrader API error X: nope")
        status = self.manager.status()
        self.assertEqual(status["sessions"]["demo"]["consecutive_timeouts"], 2)
        self.assertEqual(status["reset_count"], {"demo": 1})
        self.assertIn("demo", status["last_success_at"])
        self.assertEqual(status["recent_errors"][0][1], "demo")
        self.assertIn("nope", status["recent_errors"][0][2])

    def test_recent_errors_are_deduped_within_5_seconds(self):
        self.manager._sessions["demo"] = make_session()
        self.manager._note_error("demo", "boom")
        self.manager._note_error("demo", "boom again")
        with self.manager._status_lock:
            self.assertEqual(len(self.manager._recent_errors), 1)

    def test_reset_session_increments_reset_count(self):
        old = make_session()
        self.manager._sessions["demo"] = old
        new_client = object()
        new_session = make_session(client=new_client)
        with mock.patch.object(self.manager, "_create_session",
                               return_value=(new_client, new_session)), \
             mock.patch.object(self.manager, "_ensure_reactor_alive"):
            self.manager._note_broker_timeout("demo")
            self.manager._note_broker_timeout("demo")
        self.assertEqual(self.manager.reset_count.get("demo"), 1)


class ReactorLivenessTests(unittest.TestCase):
    def test_dead_reactor_thread_exits_for_supervised_restart(self):
        self.manager = CTraderManager()
        self.manager._reactor_started = True
        # A thread that died (is_alive() is False) forces the supervised
        # restart path. A plain fake avoids any real thread in the suite.
        self.manager._reactor_thread = SimpleNamespace(is_alive=lambda: False)
        with mock.patch("os._exit") as exit_mock:
            self.manager._ensure_reactor_alive()
        exit_mock.assert_called_once_with(1)

    def test_live_reactor_thread_does_not_exit(self):
        self.manager = CTraderManager()
        self.manager._reactor_started = True
        self.manager._reactor_thread = SimpleNamespace(is_alive=lambda: True)
        with mock.patch("os._exit") as exit_mock:
            self.manager._ensure_reactor_alive()
        exit_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
