import unittest

from app.ctrader_risk_metrics import calculate_equity_drawdowns


class CTraderEquityDrawdownTests(unittest.TestCase):
    def test_calculates_peak_and_daily_drawdown(self):
        result = calculate_equity_drawdowns(
            peak_equity=1200,
            current_equity=1080,
            day_start_equity=1140,
        )
        self.assertAlmostEqual(result["drawdown"], 10.0)
        self.assertAlmostEqual(result["daily_drawdown"], 5.2631578947)

    def test_gains_do_not_create_negative_drawdown(self):
        result = calculate_equity_drawdowns(
            peak_equity=1000,
            current_equity=1100,
            day_start_equity=1050,
        )
        self.assertEqual(result, {"drawdown": 0.0, "daily_drawdown": 0.0})

    def test_missing_or_invalid_baseline_is_unavailable(self):
        result = calculate_equity_drawdowns(
            peak_equity=None,
            current_equity=900,
            day_start_equity=0,
        )
        self.assertIsNone(result["drawdown"])
        self.assertIsNone(result["daily_drawdown"])

    def test_rejects_non_finite_values(self):
        result = calculate_equity_drawdowns(
            peak_equity=float("nan"),
            current_equity=float("inf"),
            day_start_equity=1000,
        )
        self.assertIsNone(result["drawdown"])
        self.assertIsNone(result["daily_drawdown"])


if __name__ == "__main__":
    unittest.main()
