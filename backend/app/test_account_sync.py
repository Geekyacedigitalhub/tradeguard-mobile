"""Fail-closed tests for cTrader demo risk metrics."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from .account_sync import live_account_metrics


class LiveAccountMetricsTests(unittest.TestCase):
    def _connection(self, selected, heartbeat):
        fake = MagicMock()
        db = fake.__enter__.return_value
        db.execute.side_effect = [
            MagicMock(fetchone=MagicMock(return_value=selected)),
            MagicMock(fetchone=MagicMock(return_value=heartbeat)),
        ]
        return fake, db

    def test_missing_heartbeat_never_returns_metrics(self):
        fake, _ = self._connection((123, "demo"), None)
        with patch("backend.app.account_sync.connection", return_value=fake):
            self.assertIsNone(live_account_metrics("user-1"))

    def test_stale_heartbeat_never_returns_metrics(self):
        payload = {
            "connected": True,
            "terminal": "cTrader Cloud",
            "provider": "cTrader",
            "environment": "demo",
            "account": "123",
            "balance": 1000,
            "equity": 1000,
            "today_pl": 0,
            "drawdown": 0,
            "currency": "USD",
        }
        old = datetime.now(timezone.utc) - timedelta(seconds=46)
        fake, _ = self._connection((123, "demo"), (payload, old))
        with patch("backend.app.account_sync.connection", return_value=fake):
            self.assertIsNone(live_account_metrics("user-1"))

    def test_missing_daily_pl_or_drawdown_never_returns_partial_metrics(self):
        payload = {
            "connected": True,
            "terminal": "cTrader Cloud",
            "provider": "cTrader",
            "environment": "demo",
            "account": "123",
            "balance": 1000,
            "equity": 1000,
            "currency": "USD",
        }
        fresh = datetime.now(timezone.utc)
        fake, _ = self._connection((123, "demo"), (payload, fresh))
        with patch("backend.app.account_sync.connection", return_value=fake):
            self.assertIsNone(live_account_metrics("user-1"))

    def test_live_selected_account_never_returns_demo_metrics(self):
        payload = {
            "connected": True,
            "terminal": "cTrader Cloud",
            "provider": "cTrader",
            "environment": "demo",
            "account": "123",
            "balance": 1000,
            "equity": 1000,
            "today_pl": 0,
            "drawdown": 0,
            "currency": "USD",
        }
        fresh = datetime.now(timezone.utc)
        fake, _ = self._connection((123, "live"), (payload, fresh))
        with patch("backend.app.account_sync.connection", return_value=fake):
            self.assertIsNone(live_account_metrics("user-1"))


if __name__ == "__main__":
    unittest.main()
