import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("JWT_SECRET", "unit-test-only-not-a-real-secret")

from fastapi import HTTPException
from app import main


class EmergencyStopTests(unittest.TestCase):
    def setUp(self):
        self.user = {"id": "user-123"}
        self.state = {"running": False, "emergency_stopped": True}
        self.connection = MagicMock()
        self.conn = self.connection.__enter__.return_value
        self.conn.execute.return_value.fetchone.return_value = ("user-123",)

    @patch("app.main.get_bot")
    @patch("app.main.send_push", side_effect=RuntimeError("push unavailable"))
    @patch("app.main.notification_event", side_effect=RuntimeError("history unavailable"))
    @patch("app.main.connection")
    def test_emergency_stop_remains_successful_when_alert_delivery_fails(
        self, connection, event, push, get_bot
    ):
        connection.return_value.__enter__.return_value = self.conn
        get_bot.return_value = self.state

        result = main.emergency_stop(self.user)

        self.assertTrue(result["ok"])
        self.assertTrue(result["state"]["emergency_stopped"])
        self.assertFalse(result["state"]["running"])
        event.assert_called_once()
        push.assert_called_once()
        self.conn.execute.assert_called_once()
        persisted_sql = self.conn.execute.call_args.args[0]
        self.assertIn("UPDATE bot_state", persisted_sql)
        self.assertNotIn("bridge_commands", persisted_sql)
        self.assertIn("Existing cTrader positions remain open", result["message"])

    @patch("app.main.connection")
    def test_emergency_stop_reports_uninitialized_engine(self, connection):
        conn = connection.return_value.__enter__.return_value
        conn.execute.return_value.fetchone.return_value = None

        with self.assertRaises(HTTPException) as caught:
            main.emergency_stop(self.user)

        self.assertEqual(caught.exception.status_code, 500)
        self.assertIn("Bot state is not initialized", caught.exception.detail)


    @patch("app.main.get_bot")
    @patch("app.main.connection")
    def test_clearing_emergency_latch_does_not_restart_bot(self, connection, get_bot):
        conn = connection.return_value.__enter__.return_value
        get_bot.return_value = {"running": False, "emergency_stopped": False}

        result = main.reset_emergency(self.user)

        self.assertFalse(result["running"])
        self.assertFalse(result["emergency_stopped"])
        sql = conn.execute.call_args.args[0]
        self.assertIn("running=false", sql)
        self.assertIn("emergency_stopped=false", sql)


    @patch("app.main.connection")
    def test_start_is_rejected_while_emergency_stop_is_active(self, connection):
        conn = connection.return_value.__enter__.return_value
        conn.execute.return_value.fetchone.return_value = (True,)

        with self.assertRaises(HTTPException) as caught:
            main.start_bot(self.user)

        self.assertEqual(caught.exception.status_code, 409)
        self.assertIn("Emergency stop is active", caught.exception.detail)
        self.assertEqual(conn.execute.call_count, 1)
        self.assertNotIn("running=true", conn.execute.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
