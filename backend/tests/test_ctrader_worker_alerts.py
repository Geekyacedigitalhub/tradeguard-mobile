import os
import unittest
from unittest.mock import patch

os.environ.setdefault("JWT_SECRET", "unit-test-only-not-a-real-secret")

from app.ctrader_worker import _publish_position_alert


class CTraderPositionAlertTests(unittest.TestCase):
    @patch("app.ctrader_worker.send_push")
    @patch("app.ctrader_worker.notification_event")
    def test_confirmed_close_is_logged_and_pushed(self, event, push):
        _publish_position_alert(
            "user-1", "close_position",
            {"position_id": 77, "environment": "live"},
            {"status": "confirmed_closed", "position_id": 77, "environment": "live"},
        )
        self.assertEqual(event.call_args.args[1], "notification_trade_closed")
        self.assertIn("confirmed closed", event.call_args.args[2]["status"] if "status" in event.call_args.args[2] else "confirmed closed")
        self.assertIn("confirmed", push.call_args.args[1].lower())
        self.assertEqual(push.call_args.args[3]["environment"], "live")

    @patch("app.ctrader_worker.send_push")
    @patch("app.ctrader_worker.notification_event")
    def test_partial_close_warns_to_check_remaining_volume(self, event, push):
        _publish_position_alert(
            "user-1", "close_position",
            {"position_id": 78, "environment": "demo"},
            {"status": "confirmed_reduced", "position_id": 78, "environment": "demo"},
        )
        self.assertEqual(event.call_args.args[1], "notification_trade_partially_closed")
        self.assertIn("remaining volume", push.call_args.args[2])

    @patch("app.ctrader_worker.send_push")
    @patch("app.ctrader_worker.notification_event")
    def test_unconfirmed_close_does_not_claim_position_is_closed(self, event, push):
        _publish_position_alert(
            "user-1", "close_position",
            {"position_id": 79, "environment": "live"},
            {"status": "submitted_unconfirmed", "position_id": 79, "environment": "live"},
        )
        self.assertEqual(event.call_args.args[1], "notification_trade_close_unconfirmed")
        self.assertIn("before retrying", push.call_args.args[2])

    @patch("app.ctrader_worker.send_push")
    @patch("app.ctrader_worker.notification_event")
    def test_protection_failure_advises_broker_check(self, event, push):
        _publish_position_alert(
            "user-1", "protect_position",
            {"position_id": 80, "environment": "demo"},
            {"error": "broker timeout"},
            failed=True,
        )
        self.assertEqual(event.call_args.args[1], "notification_protection_failed")
        self.assertIn("at the broker", push.call_args.args[2])

    @patch("app.ctrader.worker.send_push", create=True)
    def test_non_position_command_does_not_send_position_alert(self, push):
        with patch("app.ctrader_worker.notification_event") as event:
            _publish_position_alert("user-1", "open_market", {}, {"status": "failed"}, failed=True)
        event.assert_not_called()


if __name__ == "__main__":
    unittest.main()
