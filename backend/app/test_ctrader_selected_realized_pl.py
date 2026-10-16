"""Regression tests for selected cTrader demo-account P/L consistency."""
import unittest
from unittest.mock import MagicMock, patch

from .ctrader_selected_realized_pl import selected_account_realized_pl


class SelectedAccountRealizedPLTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.context = MagicMock()
        self.conn = self.context.__enter__.return_value
        self.connection = patch(
            "backend.app.ctrader_selected_realized_pl.connection",
            return_value=self.context,
        )
        self.connection.start()
        self.addCleanup(self.connection.stop)
        self.ready = patch(
            "backend.app.ctrader_selected_realized_pl.manager.account_ready",
            return_value=True,
        )
        self.ready.start()
        self.addCleanup(self.ready.stop)
        self.history = patch(
            "backend.app.ctrader_selected_realized_pl.realized_pl_for_utc_day",
        )
        self.fetch_history = self.history.start()
        self.addCleanup(self.history.stop)
        self.fetch_history.return_value = {
            "realized_net_pnl": 12.5,
            "history_complete": True,
            "status": "broker_close_deal_components_summed",
        }

    async def test_returns_pnl_when_account_selection_is_stable(self):
        self.conn.execute.return_value.fetchone.side_effect = [
            (123, "demo"), (123, "demo")
        ]
        result = await selected_account_realized_pl("user-1")
        self.assertEqual(result["account_id"], 123)
        self.assertEqual(result["realized_net_pnl"], 12.5)
        self.assertFalse(result["risk_metrics_verified"])
        self.assertEqual(self.conn.execute.call_count, 2)

    async def test_rejects_account_change_during_history_fetch(self):
        self.conn.execute.return_value.fetchone.side_effect = [
            (123, "demo"), (456, "demo")
        ]
        with self.assertRaisesRegex(RuntimeError, "changed or disconnected"):
            await selected_account_realized_pl("user-1")

    async def test_rejects_environment_change_during_history_fetch(self):
        self.conn.execute.return_value.fetchone.side_effect = [
            (123, "demo"), (123, "live")
        ]
        with self.assertRaisesRegex(RuntimeError, "changed or disconnected"):
            await selected_account_realized_pl("user-1")

    async def test_rejects_invalid_account_id_before_history_fetch(self):
        for invalid_id in (True, 123.5, "123.5", 0, -1):
            with self.subTest(account_id=invalid_id):
                self.conn.execute.return_value.fetchone.return_value = (
                    invalid_id, "demo"
                )
                with self.assertRaises((RuntimeError, ValueError, TypeError)):
                    await selected_account_realized_pl("user-1")
                self.fetch_history.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
