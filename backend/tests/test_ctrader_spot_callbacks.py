import unittest

from app.ctrader_service import CTraderManager


class CTraderSpotCallbackTests(unittest.TestCase):
    def setUp(self):
        self.manager = CTraderManager()

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


if __name__ == "__main__":
    unittest.main()
