"""Unit tests for pure cTrader drawdown math; no database or broker required."""
import math
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from .ctrader_metric_history import (
    drawdown_percent_from_peak,
    record_demo_equity_snapshot,
)


class DrawdownPercentFromPeakTests(unittest.TestCase):
    def test_calculates_percentage_from_peak(self):
        self.assertEqual(drawdown_percent_from_peak(1000, 900), 10.0)

    def test_no_drawdown_at_or_above_peak(self):
        self.assertEqual(drawdown_percent_from_peak(1000, 1000), 0.0)
        self.assertEqual(drawdown_percent_from_peak(1000, 1100), 0.0)

    def test_zero_current_equity_is_full_drawdown(self):
        self.assertEqual(drawdown_percent_from_peak(1000, 0), 100.0)

    def test_rejects_zero_or_invalid_peak(self):
        self.assertIsNone(drawdown_percent_from_peak(0, 0))
        self.assertIsNone(drawdown_percent_from_peak(None, 900))
        self.assertIsNone(drawdown_percent_from_peak(True, 900))

    def test_rejects_non_finite_or_negative_metrics(self):
        self.assertIsNone(drawdown_percent_from_peak(math.inf, 900))
        self.assertIsNone(drawdown_percent_from_peak(1000, math.nan))
        self.assertIsNone(drawdown_percent_from_peak(1000, -1))



class RecordDemoEquitySnapshotTests(unittest.TestCase):
    def test_rejects_account_switch_before_writing(self):
        fake_connection = MagicMock()
        fake_connection.__enter__.return_value.execute.return_value.fetchone.return_value = (456, "demo")
        with patch("app.ctrader_metric_history.connection", return_value=fake_connection):
            with self.assertRaisesRegex(ValueError, "currently selected demo account"):
                record_demo_equity_snapshot(
                    user_id="user-1",
                    account_id=123,
                    environment="demo",
                    balance=1000,
                    equity=1000,
                    currency="USD",
                    observed_at=datetime(2026, 10, 15, tzinfo=timezone.utc),
                )
        self.assertEqual(fake_connection.__enter__.return_value.execute.call_count, 1)

    def test_rejects_live_environment_before_database_access(self):
        with patch("app.ctrader_metric_history.connection") as connection_mock:
            with self.assertRaisesRegex(ValueError, "Only cTrader demo"):
                record_demo_equity_snapshot(
                    user_id="user-1",
                    account_id=123,
                    environment="live",
                    balance=1000,
                    equity=1000,
                    currency="USD",
                )
            connection_mock.assert_not_called()

    def test_rejects_naive_timestamp_before_database_access(self):
        with patch("app.ctrader_metric_history.connection") as connection_mock:
            with self.assertRaisesRegex(ValueError, "timezone-aware"):
                record_demo_equity_snapshot(
                    user_id="user-1",
                    account_id=123,
                    environment="demo",
                    balance=1000,
                    equity=1000,
                    currency="USD",
                    observed_at=datetime(2026, 10, 15),
                )
            connection_mock.assert_not_called()

if __name__ == "__main__":
    unittest.main()
