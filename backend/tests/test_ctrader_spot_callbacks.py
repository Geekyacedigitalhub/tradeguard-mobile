import unittest

from app.ctrader_service import CTraderManager


class CTraderSpotCallbackTests(unittest.TestCase):
    def setUp(self):
        self.manager = CTraderManager()

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
