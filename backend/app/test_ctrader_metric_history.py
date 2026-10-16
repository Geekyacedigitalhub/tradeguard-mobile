"""Unit tests for pure cTrader drawdown math; no database or broker required."""
import math
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

from . import ctrader_metric_history as metric_history
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

    def test_persists_selected_demo_snapshot_and_returns_unverified_drawdown(self):
        instant = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
        history_start = datetime(2026, 10, 14, 12, tzinfo=timezone.utc)
        fake_connection = MagicMock()
        db = fake_connection.__enter__.return_value
        db.execute.side_effect = [
            MagicMock(fetchone=MagicMock(return_value=(123, "demo"))),
            MagicMock(),
            MagicMock(fetchone=MagicMock(return_value=(Decimal("1000"), Decimal("950"), "USD"))),
            MagicMock(fetchone=MagicMock(return_value=(Decimal("1000"), history_start))),
        ]
        with patch.object(metric_history, "connection", return_value=fake_connection):
            result = record_demo_equity_snapshot(
                user_id="user-1",
                account_id=123,
                environment="demo",
                balance="1000",
                equity="950",
                currency="USD",
                observed_at=instant,
            )
        self.assertEqual(result["drawdown"], 5.0)
        self.assertEqual(result["drawdown_status"], "tracking_period_peak_only")
        self.assertFalse(result["drawdown_verified"])
        self.assertEqual(result["peak_equity"], 1000.0)
        self.assertEqual(result["history_start"], history_start.isoformat())
        self.assertEqual(db.execute.call_count, 4)

    def test_rejects_conflicting_existing_snapshot(self):
        fake_connection = MagicMock()
        db = fake_connection.__enter__.return_value
        db.execute.side_effect = [
            MagicMock(fetchone=MagicMock(return_value=(123, "demo"))),
            MagicMock(),
            MagicMock(fetchone=MagicMock(return_value=(Decimal("1000"), Decimal("999"), "USD"))),
        ]
        with patch.object(metric_history, "connection", return_value=fake_connection):
            with self.assertRaisesRegex(ValueError, "Conflicting snapshot"):
                record_demo_equity_snapshot(
                    user_id="user-1",
                    account_id=123,
                    environment="demo",
                    balance=1000,
                    equity=950,
                    currency="USD",
                    observed_at=datetime(2026, 10, 15, 12, tzinfo=timezone.utc),
                )


    def test_rejects_invalid_account_and_metrics_before_database_access(self):
        invalid_cases = [
            {"account_id": True, "balance": 1000, "equity": 1000, "currency": "USD"},
            {"account_id": 123, "balance": -1, "equity": 1000, "currency": "USD"},
            {"account_id": 123, "balance": 1000, "equity": float("inf"), "currency": "USD"},
            {"account_id": 123, "balance": 1000, "equity": 1000, "currency": "usd"},
            {"account_id": 123, "balance": 1000, "equity": 1000, "currency": "US"},
        ]
        for values in invalid_cases:
            with self.subTest(values=values):
                with patch.object(metric_history, "connection") as connection_mock:
                    with self.assertRaises(ValueError):
                        record_demo_equity_snapshot(
                            user_id="user-1",
                            environment="demo",
                            observed_at=datetime(2026, 10, 15, tzinfo=timezone.utc),
                            **values,
                        )
                    connection_mock.assert_not_called()

    def test_rejects_account_switch_before_writing(self):
        fake_connection = MagicMock()
        fake_connection.__enter__.return_value.execute.return_value.fetchone.return_value = (456, "demo")
        with patch.object(metric_history, "connection", return_value=fake_connection):
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
