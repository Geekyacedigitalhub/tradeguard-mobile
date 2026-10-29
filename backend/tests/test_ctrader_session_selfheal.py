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
- a dead reactor thread exits the process for a supervised restart.
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

    def test_resets_are_rate_limited_within_60_seconds(self):
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
