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

    def test_last_callback_removal_cleans_up_user_entry(self):
        callback = lambda event: None
        self.manager.register_spot_callback("user-1", callback)

        self.manager.unregister_spot_callback("user-1", callback)

        with self.manager._spot_lock:
            self.assertNotIn("user-1", self.manager._spot_callbacks)


if __name__ == "__main__":
    unittest.main()
