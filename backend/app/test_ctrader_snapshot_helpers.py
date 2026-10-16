"""Regression tests for cTrader broker snapshot normalization helpers."""

import math
import unittest
from types import SimpleNamespace

from .ctrader_snapshot_helpers import (
    normalize_currency_code,
    normalize_trade_side,
    positive_integer,
    scale_balance,
    scale_unrealized_pnl,
)



class NormalizeCurrencyCodeTests(unittest.TestCase):
    def test_normalizes_three_letter_ascii_currency(self):
        self.assertEqual(normalize_currency_code("USD"), "USD")
        self.assertEqual(normalize_currency_code(" usd "), "USD")

    def test_rejects_malformed_currency_values(self):
        for value in (None, True, "", "US", "USDD", "U$D", "€UR", "UＳD"):
            with self.subTest(value=value):
                self.assertIsNone(normalize_currency_code(value))


class NormalizeTradeSideTests(unittest.TestCase):
    def test_maps_known_sides(self):
        self.assertEqual(normalize_trade_side(1), "BUY")
        self.assertEqual(normalize_trade_side(2), "SELL")

    def test_rejects_unknown_or_malformed_sides(self):
        for value in (None, True, 0, 3, "1.0", 1.5, "unknown"):
            with self.subTest(value=value):
                self.assertEqual(normalize_trade_side(value), "UNKNOWN")


class ScaleBalanceTests(unittest.TestCase):
    def test_scales_integer_minor_units(self):
        self.assertEqual(scale_balance(123456, 2), 1234.56)
        self.assertEqual(scale_balance(123456, "2"), 1234.56)

    def test_rejects_missing_invalid_or_non_finite_values(self):
        invalid = (
            (None, 2),
            (100, None),
            (True, 2),
            (100, True),
            (100, -1),
            (100, 13),
            (100, 1.5),
            (math.inf, 2),
            (math.nan, 2),
            ("not-a-number", 2),
            (100.0, 2),
            (2**53 + 1, 0),
        )
        for raw_balance, digits in invalid:
            with self.subTest(raw_balance=raw_balance, digits=digits):
                self.assertIsNone(scale_balance(raw_balance, digits))


class PositiveIntegerTests(unittest.TestCase):
    def test_accepts_only_positive_whole_numbers(self):
        self.assertEqual(positive_integer(42), 42)
        self.assertEqual(positive_integer("42"), 42)
        for value in (None, True, 0, -1, 1.5, "1.5", "bad"):
            with self.subTest(value=value):
                self.assertIsNone(positive_integer(value))


class ScaleUnrealizedPnlTests(unittest.TestCase):
    def test_scales_complete_broker_rows(self):
        rows = [
            SimpleNamespace(netUnrealizedPnL=125),
            SimpleNamespace(netUnrealizedPnL=-25),
        ]
        self.assertEqual(scale_unrealized_pnl(rows, 2), 1.0)

    def test_empty_complete_rows_mean_zero(self):
        self.assertEqual(scale_unrealized_pnl([], 2), 0.0)

    def test_rejects_aggregate_overflow(self):
        rows = [
            SimpleNamespace(netUnrealizedPnL=2**53),
            SimpleNamespace(netUnrealizedPnL=1),
        ]
        self.assertIsNone(scale_unrealized_pnl(rows, 2))

    def test_rejects_floating_point_money_values(self):
        for value in (1.0, 1.5, math.inf, math.nan):
            with self.subTest(value=value):
                self.assertIsNone(scale_unrealized_pnl(
                    [SimpleNamespace(netUnrealizedPnL=value)], 2
                ))

    def test_rejects_partial_or_malformed_pnl(self):
        invalid_rows = (
            None,
            "not rows",
            [{"netUnrealizedPnL": 10}],
            [SimpleNamespace(netUnrealizedPnL=None)],
            [SimpleNamespace(netUnrealizedPnL=math.inf)],
            [SimpleNamespace(netUnrealizedPnL=True)],
        )
        for rows in invalid_rows:
            with self.subTest(rows=rows):
                self.assertIsNone(scale_unrealized_pnl(rows, 2))


if __name__ == "__main__":
    unittest.main()
