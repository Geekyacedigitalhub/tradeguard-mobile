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
        self.assertEqual(event.call_args.args[2]["status"], "confirmed_closed")
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

    @patch("app.ctrader_worker.send_push")
    @patch("app.ctrader_worker.notification_event", side_effect=RuntimeError("history unavailable"))
    def test_push_is_attempted_even_if_alert_history_write_fails(self, event, push):
        _publish_position_alert(
            "user-1", "close_position",
            {"position_id": 81, "environment": "live"},
            {"status": "confirmed_closed", "position_id": 81, "environment": "live"},
        )
        event.assert_called_once()
        push.assert_called_once()

    def test_non_position_command_does_not_send_position_alert(self):
        with patch("app.ctrader_worker.notification_event") as event, patch("app.ctrader_worker.send_push") as push:
            _publish_position_alert("user-1", "open_market", {}, {"status": "failed"}, failed=True)
        event.assert_not_called()
        push.assert_not_called()



    @patch("app.ctrader_worker.send_push")
    @patch("app.ctrader_worker.notification_event")
    def test_close_all_fully_confirmed_is_reported_as_confirmed(self, event, push):
        result = {
            "status": "confirmed_closed",
            "environment": "live",
            "attempted_count": 2,
            "confirmed_closed_count": 2,
            "positions": [
                {"position_id": 91, "status": "confirmed_closed"},
                {"position_id": 92, "status": "confirmed_closed"},
            ],
        }
        _publish_position_alert(
            "user-1", "close_all_positions",
            {"environment": "live", "manual_close": True}, result,
        )
        self.assertEqual(event.call_args.args[1], "notification_close_all_confirmed")
        self.assertEqual(event.call_args.args[2]["result"]["confirmed_closed_count"], 2)
        self.assertIn("2 positions closed", push.call_args.args[2])

    @patch("app.ctrader_worker.send_push")
    @patch("app.ctrader_worker.notification_event")
    def test_partial_close_all_warns_to_check_broker(self, event, push):
        result = {
            "status": "partially_closed",
            "environment": "live",
            "attempted_count": 3,
            "confirmed_closed_count": 1,
            "positions": [
                {"position_id": 93, "status": "confirmed_closed"},
                {"position_id": 94, "status": "unconfirmed"},
                {"position_id": 95, "status": "failed"},
            ],
        }
        _publish_position_alert(
            "user-1", "close_all_positions",
            {"environment": "live", "manual_close": True}, result,
        )
        self.assertEqual(event.call_args.args[1], "notification_close_all_unconfirmed")
        self.assertIn("1/3 positions confirmed closed", push.call_args.args[2])
        self.assertIn("Check the broker account now", push.call_args.args[2])

    @patch("app.ctrader_worker.send_push")
    @patch("app.ctrader_worker.notification_event")
    def test_close_all_with_no_open_positions_is_confirmed(self, event, push):
        _publish_position_alert(
            "user-1", "close_all_positions",
            {"environment": "demo", "manual_close": True},
            {
                "status": "no_open_positions",
                "environment": "demo",
                "attempted_count": 0,
                "confirmed_closed_count": 0,
                "positions": [],
            },
        )
        self.assertEqual(event.call_args.args[1], "notification_close_all_confirmed")
        self.assertIn("confirmed 0 positions closed", push.call_args.args[2])

if __name__ == "__main__":
    unittest.main()
