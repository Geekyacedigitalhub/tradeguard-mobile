"""Fail-closed tests for the read-only cTrader account overview."""
import math
import unittest
from unittest.mock import patch

from .ctrader_account_overview_api import account_overview


class AccountOverviewTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.snapshot = patch(
            "backend.app.ctrader_account_overview_api.ctrader_account_snapshot",
            return_value={"account_id": 123, "environment": "demo", "balance": 1000},
        )
        self.fetch_snapshot = self.snapshot.start()
        self.addCleanup(self.snapshot.stop)
        self.realized = patch(
            "backend.app.ctrader_account_overview_api.selected_account_realized_pl"
        )
        self.fetch_realized = self.realized.start()
        self.addCleanup(self.realized.stop)
        self.fetch_realized.return_value = {
            "account_id": 123,
            "environment": "demo",
            "realized_net_pnl": 12.5,
            "history_complete": True,
            "status": "broker_close_deal_components_summed",
            "source": "ctrader_close_deal_history",
            "window_start": "2026-10-15T00:00:00+00:00",
            "as_of": "2026-10-15T12:00:00+00:00",
        }

    async def test_exposes_pnl_only_for_complete_matching_demo_history(self):
        result = await account_overview({"id": "user-1"})
        self.assertEqual(result["today_pl"], 12.5)
        self.assertEqual(result["realized_daily_pl"], 12.5)
        self.assertTrue(result["realized_daily_pl_history_complete"])
        self.assertFalse(result["risk_metrics_verified"])

    async def test_withholds_pnl_when_history_is_incomplete(self):
        self.fetch_realized.return_value["history_complete"] = False
        result = await account_overview({"id": "user-1"})
        self.assertIsNone(result["today_pl"])
        self.assertIsNone(result["realized_daily_pl"])
        self.assertFalse(result["realized_daily_pl_history_complete"])

    async def test_withholds_non_finite_boolean_and_string_pnl(self):
        for value in (True, "12.5", math.nan, math.inf, -math.inf):
            with self.subTest(value=value):
                self.fetch_realized.return_value["realized_net_pnl"] = value
                result = await account_overview({"id": "user-1"})
                self.assertIsNone(result["today_pl"])
                self.assertIsNone(result["realized_daily_pl"])

    async def test_withholds_pnl_for_account_or_environment_mismatch(self):
        for field, value in (("account_id", 456), ("environment", "live")):
            with self.subTest(field=field):
                self.fetch_realized.return_value[field] = value
                result = await account_overview({"id": "user-1"})
                self.assertIsNone(result["today_pl"])
                self.assertIsNone(result["realized_daily_pl"])
                self.assertFalse(result["realized_daily_pl_history_complete"])

    async def test_withholds_pnl_when_history_metadata_is_missing(self):
        for field in ("source", "window_start", "as_of"):
            with self.subTest(field=field):
                self.fetch_realized.return_value.pop(field, None)
                result = await account_overview({"id": "user-1"})
                self.assertIsNone(result["today_pl"])
                self.assertIsNone(result["realized_daily_pl"])

    async def test_never_marks_risk_metrics_verified(self):
        self.fetch_realized.return_value["risk_metrics_verified"] = True
        result = await account_overview({"id": "user-1"})
        self.assertFalse(result["risk_metrics_verified"])
        self.assertEqual(
            result["risk_metrics_status"],
            "daily_drawdown_and_persistent_risk_verification_unavailable",
        )

    async def test_history_failure_keeps_account_snapshot_but_withholds_pnl(self):
        self.fetch_realized.side_effect = RuntimeError("history unavailable")
        result = await account_overview({"id": "user-1"})
        self.assertEqual(result["balance"], 1000)
        self.assertIsNone(result["today_pl"])
        self.assertIsNone(result["realized_daily_pl"])
        self.assertFalse(result["risk_metrics_verified"])


if __name__ == "__main__":
    unittest.main()
