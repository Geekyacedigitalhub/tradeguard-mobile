"""Unit tests for pure cTrader drawdown math; no database or broker required."""
import math
import unittest

from .ctrader_metric_history import drawdown_percent_from_peak


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


if __name__ == "__main__":
    unittest.main()
