import unittest

from app.ctrader_service import CTraderManager


class CTraderSpotCallbackTests(unittest.TestCase):
    def setUp(self):
        self.manager = CTraderManager()

    def test_stream_filter_rejects_other_accounts_and_unsubscribed_symbols(self):
        from app.ctrader_service import filter_spot_tick_for_stream
        tick = {"type": "tick", "account_id": 42, "symbol_id": 7, "price": 1.2}
        names = {7: "EURUSD"}
        self.assertIsNone(filter_spot_tick_for_stream(tick, 99, names))
        self.assertIsNone(filter_spot_tick_for_stream({**tick, "symbol_id": 8}, 42, names))
        self.assertEqual(
            filter_spot_tick_for_stream(tick, 42, names)["symbol"], "EURUSD"
        )
        self.assertIsNone(
            filter_spot_tick_for_stream({**tick, "account_id": "invalid"}, 42, names)
        )
        self.assertIsNone(
            filter_spot_tick_for_stream({**tick, "account_id": True}, 1, names)
        )
        self.assertIsNone(
            filter_spot_tick_for_stream({**tick, "symbol_id": True}, 42, {1: "EURUSD"})
        )
        self.assertIsNone(
            filter_spot_tick_for_stream({**tick, "account_id": 42.9}, 42, names)
        )
        self.assertIsNone(
            filter_spot_tick_for_stream({**tick, "symbol_id": 7.9}, 42, names)
        )
        self.assertIsNone(
            filter_spot_tick_for_stream({**tick, "symbol_id": "7.0"}, 42, names)
        )

    def test_spot_tick_payload_preserves_account_identity(self):
        from app.ctrader_service import build_spot_tick_payload
        payload = build_spot_tick_payload(
            42, 7, {"bid": 1.2, "ask": 1.3, "timestamp": 123456}
        )
        self.assertEqual(payload["account_id"], 42)
        self.assertEqual(payload["symbol_id"], 7)
        self.assertEqual(payload["price"], 1.25)
        self.assertEqual(payload["time_msc"], 123456)

    def test_quote_event_without_valid_prices_does_not_refresh_cached_quote(self):
        from app.ctrader_service import merge_spot_quote
        previous = {"bid": 1.2345, "ask": 1.2347, "timestamp": 100}
        result = merge_spot_quote(previous, 0, None, 200, 4)
        self.assertIsNone(result)
        self.assertEqual(previous["timestamp"], 100)

    def test_partial_quote_updates_only_valid_side_and_timestamp(self):
        from app.ctrader_service import merge_spot_quote
        previous = {"bid": 1.2345, "ask": 1.2347, "timestamp": 100}
        result = merge_spot_quote(previous, None, 12349, 200, 4)
        self.assertEqual(result, {"bid": 1.2345, "ask": 1.2349, "timestamp": 200})
        self.assertEqual(previous["ask"], 1.2347)

    def test_multiple_mobile_streams_receive_independent_callbacks(self):
        first_events = []
        second_events = []
        first = first_events.append
        second = second_events.append

        self.manager.register_spot_callback("user-1", first)
        self.manager.register_spot_callback("user-1", second)

        with self.manager._spot_lock:
            callbacks = tuple(self.manager._spot_callbacks["user-1"])
        event = {"type": "tick", "symbol_id": 12, "price": 1.25}
        for callback in callbacks:
            callback(event)

        self.assertEqual(first_events, [event])
        self.assertEqual(second_events, [event])

    def test_disconnect_removes_only_that_stream_callback(self):
        first = lambda event: None
        second = lambda event: None
        self.manager.register_spot_callback("user-1", first)
        self.manager.register_spot_callback("user-1", second)

        self.manager.unregister_spot_callback("user-1", first)

        with self.manager._spot_lock:
            self.assertEqual(self.manager._spot_callbacks["user-1"], {second})

    def test_existing_same_user_subscription_increments_reference_count(self):
        import asyncio
        from types import SimpleNamespace
        session = SimpleNamespace(
            spot_subscriptions={(42, 7): "user-1"},
            spot_subscription_refs={(42, 7): 1},
            latest_spots={(42, 7): {"bid": 1.2}},
            authorized_accounts={42},
            symbol_digits={(42, 7): 5},
        )
        self.manager._sessions["demo"] = session
        self.manager._session = lambda environment: session
        result = asyncio.run(self.manager.subscribe_spots("user-1", 42, 7, "token", "demo"))
        self.assertEqual(result, {"bid": 1.2})
        self.assertEqual(session.spot_subscription_refs[(42, 7)], 2)

    def test_concurrent_same_symbol_subscriptions_share_one_broker_request(self):
        import asyncio
        from types import SimpleNamespace
        session = SimpleNamespace(
            spot_subscriptions={},
            spot_subscription_refs={},
            latest_spots={},
            authorized_accounts={42},
            symbol_digits={(42, 7): 5},
        )
        self.manager._session = lambda environment: session
        sends = []

        # The CI environment may load the service without the optional SDK
        # protobuf symbols, so provide the minimal request shape for this unit test.
        import app.ctrader_service as service_module
        class FakeSubscribeRequest:
            def __init__(self):
                self.ctidTraderAccountId = 0
                self.symbolId = []
                self.subscribeToSpotTimestamp = False
        service_module.ProtoOASubscribeSpotsReq = FakeSubscribeRequest

        async def fake_send(environment, request, timeout=None):
            sends.append(request)
            await asyncio.sleep(0.01)
            return {"ok": True}

        self.manager._send = fake_send

        async def run():
            await asyncio.gather(
                self.manager.subscribe_spots("user-1", 42, 7, "token", "demo"),
                self.manager.subscribe_spots("user-1", 42, 7, "token", "demo"),
            )

        asyncio.run(run())
        self.assertEqual(len(sends), 1)
        self.assertEqual(session.spot_subscription_refs[(42, 7)], 2)

    def test_disconnect_decrements_reference_without_broker_unsubscribe(self):
        import asyncio
        from types import SimpleNamespace
        session = SimpleNamespace(
            spot_subscriptions={(42, 7): "user-1"},
            spot_subscription_refs={(42, 7): 2},
            latest_spots={(42, 7): {"bid": 1.2}},
        )
        self.manager._sessions["demo"] = session
        async def unexpected_send(*args, **kwargs):
            raise AssertionError("Broker unsubscribe should wait for the last stream")
        self.manager._send = unexpected_send
        asyncio.run(self.manager.unsubscribe_spots("user-1", 42, 7, "demo"))
        self.assertEqual(session.spot_subscription_refs[(42, 7)], 1)
        self.assertIn((42, 7), session.spot_subscriptions)
        self.assertIn((42, 7), session.latest_spots)

    def test_last_callback_removal_cleans_up_user_entry(self):
        callback = lambda event: None
        self.manager.register_spot_callback("user-1", callback)

        self.manager.unregister_spot_callback("user-1", callback)

        with self.manager._spot_lock:
            self.assertNotIn("user-1", self.manager._spot_callbacks)


    def test_disconnect_invalidates_cached_market_data_and_authorization(self):
        from types import SimpleNamespace

        session = SimpleNamespace(
            ready=True,
            authorized_accounts={42},
            spot_subscriptions={(42, 7): "user-1"},
            spot_subscription_refs={(42, 7): 1},
            latest_spots={(42, 7): {"bid": 1.2, "ask": 1.3}},
            symbol_digits={(42, 7): 5},
            waiters={},
            spot_waiters={},
        )
        self.manager._sessions["demo"] = session
        events = []
        self.manager.register_spot_callback("user-1", events.append)

        self.manager._disconnected("demo", "test disconnect")

        self.assertFalse(session.ready)
        self.assertEqual(session.authorized_accounts, set())
        self.assertEqual(session.spot_subscriptions, {})
        self.assertEqual(session.spot_subscription_refs, {})
        self.assertEqual(session.latest_spots, {})
        self.assertEqual(session.symbol_digits, {})
        self.assertTrue(any(
            event.get("type") == "stream_error" and "disconnected" in event.get("message", "").lower()
            for event in events
        ))


    def test_account_list_response_does_not_overwrite_heartbeat_owner_map(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        import app.ctrader_service as service_module

        class FakeApplicationAuthResponse:
            payloadType = 1

        class FakeAccountListResponse:
            payloadType = 2

        class FakeProtobuf:
            @staticmethod
            def extract(message):
                return SimpleNamespace(ctidTraderAccount=[
                    SimpleNamespace(ctidTraderAccountId=42, isLive=True, traderLogin=1234)
                ])

        session = SimpleNamespace(
            accounts={42: "user-1"},
            waiters={},
        )
        self.manager._sessions["live"] = session
        message = SimpleNamespace(payloadType=2, clientMsgId="account-list-test")

        with patch.object(service_module, "ProtoOAApplicationAuthRes", FakeApplicationAuthResponse), \
             patch.object(service_module, "ProtoOAGetAccountListByAccessTokenRes", FakeAccountListResponse), \
             patch.object(service_module, "Protobuf", FakeProtobuf):
            self.manager._message("live", object(), message)

        self.assertEqual(session.accounts, {42: "user-1"})


    def test_new_subscription_after_disconnect_reauthorizes_and_resubscribes(self):
        import asyncio
        from types import SimpleNamespace
        import app.ctrader_service as service_module

        session = SimpleNamespace(
            ready=False,
            spot_subscriptions={},
            spot_subscription_refs={},
            latest_spots={},
            authorized_accounts=set(),
            symbol_digits={(42, 7): 5},
        )
        self.manager._session = lambda environment: session
        calls = {"authorize": 0, "subscribe": 0}

        async def fake_authorize(account_id, access_token, environment):
            calls["authorize"] += 1
            session.authorized_accounts.add(account_id)
            return {"authorized": True}

        async def fake_send(environment, request, timeout=None):
            calls["subscribe"] += 1
            return {"ok": True}

        self.manager.authorize_account = fake_authorize
        self.manager._send = fake_send

        class FakeSubscribeRequest:
            def __init__(self):
                self.ctidTraderAccountId = 0
                self.symbolId = []
                self.subscribeToSpotTimestamp = False

        service_module.ProtoOASubscribeSpotsReq = FakeSubscribeRequest

        result = asyncio.run(
            self.manager.subscribe_spots("user-1", 42, 7, "fresh-token", "demo")
        )

        self.assertIsNone(result)
        self.assertEqual(calls, {"authorize": 1, "subscribe": 1})
        self.assertEqual(session.spot_subscriptions[(42, 7)], "user-1")
        self.assertEqual(session.spot_subscription_refs[(42, 7)], 1)


    def test_account_authorization_rejects_mismatched_broker_account_id(self):
        import asyncio
        from types import SimpleNamespace
        import app.ctrader_service as service_module

        session = SimpleNamespace(authorized_accounts=set())
        self.manager._session = lambda environment: session

        class FakeAccountAuthRequest:
            def __init__(self):
                self.ctidTraderAccountId = 0
                self.accessToken = ""

        service_module.ProtoOAAccountAuthReq = FakeAccountAuthRequest

        async def fake_send(environment, request, timeout=None):
            return SimpleNamespace(ctidTraderAccountId=99)

        self.manager._send = fake_send

        with self.assertRaisesRegex(RuntimeError, "does not match"):
            asyncio.run(self.manager.authorize_account(42, "token", "demo"))

        self.assertNotIn(42, session.authorized_accounts)
        self.assertNotIn(99, session.authorized_accounts)


    def test_heartbeat_omits_account_until_reauthorized_after_reconnect(self):
        from types import SimpleNamespace

        session = SimpleNamespace(
            ready=True,
            accounts={42: "user-1"},
            authorized_accounts=set(),
        )
        self.manager._sessions["demo"] = session

        # A transport-level application-auth success is not enough to claim
        # the broker account is ready after disconnect cleared account auth.
        self.assertEqual(self.manager.heartbeat_snapshot(), [])

        session.authorized_accounts.add(42)
        # Once the account is explicitly reauthorized, it can be reported.
        # Avoid database side effects by checking the eligible rows with a
        # connection mock that accepts the heartbeat insert.
        from unittest.mock import patch
        class FakeConnection:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def execute(self, *args):
                return None

        with patch("app.ctrader_service.connection", return_value=FakeConnection()):
            self.assertEqual(self.manager.heartbeat_snapshot(), [("demo", 42, "user-1")])


    def test_disconnect_fails_and_clears_all_request_waiters(self):
        from concurrent.futures import Future
        from types import SimpleNamespace

        regular = Future()
        spot = Future()
        session = SimpleNamespace(waiters={"request-1": regular}, spot_waiters={"spot-1": spot})
        self.manager._sessions["demo"] = session

        self.manager._fail_all("demo", "cTrader disconnected")

        self.assertEqual(session.waiters, {})
        self.assertEqual(session.spot_waiters, {})
        for future in (regular, spot):
            self.assertTrue(future.done())
            with self.assertRaisesRegex(RuntimeError, "disconnected"):
                future.result()


    def test_account_auth_message_does_not_cache_unvalidated_account(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        import app.ctrader_service as service_module

        class FakeAccountAuthResponse:
            payloadType = 77

        class FakeProtobuf:
            @staticmethod
            def extract(message):
                return SimpleNamespace(ctidTraderAccountId=99)

        session = SimpleNamespace(authorized_accounts=set(), waiters={})
        self.manager._sessions["demo"] = session
        message = SimpleNamespace(payloadType=77, clientMsgId="auth-1")

        with patch.object(service_module, "ProtoOAAccountAuthRes", FakeAccountAuthResponse), \
             patch.object(service_module, "Protobuf", FakeProtobuf):
            self.manager._message("demo", object(), message)

        self.assertEqual(session.authorized_accounts, set())


if __name__ == "__main__":
    unittest.main()
