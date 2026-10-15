import unittest
from types import SimpleNamespace

from app.ctrader_snapshot_helpers import normalize_trade_side, scale_balance, scale_unrealized_pnl


class CTraderSnapshotHelpersTests(unittest.TestCase):
    def test_normalizes_known_trade_sides(self):
        self.assertEqual(normalize_trade_side(1), "BUY")
        self.assertEqual(normalize_trade_side(2), "SELL")

    def test_unknown_or_invalid_trade_side_fails_closed(self):
        for value in (None, 0, 3, "bad", 1.5, True, object()):
            with self.subTest(value=repr(value)):
                self.assertEqual(normalize_trade_side(value), "UNKNOWN")

    def test_scales_balance_with_money_digits(self):
        self.assertEqual(scale_balance(123456, 2), 1234.56)
        self.assertEqual(scale_balance(123456, 0), 123456.0)

    def test_scales_broker_unrealized_pnl_using_money_digits(self):
        rows = [
            SimpleNamespace(netUnrealizedPnL=1250),
            SimpleNamespace(netUnrealizedPnL=-250),
        ]
        self.assertEqual(scale_unrealized_pnl(rows, 2), 10.0)
        self.assertEqual(scale_unrealized_pnl([], 2), 0.0)

    def test_invalid_or_incomplete_broker_pnl_remains_unknown(self):
        invalid_rows = [
            None,
            [SimpleNamespace(netUnrealizedPnL=None)],
            [SimpleNamespace(netUnrealizedPnL=float("nan"))],
            [SimpleNamespace(netUnrealizedPnL=float("inf"))],
            [SimpleNamespace(netUnrealizedPnL=True)],
            [SimpleNamespace(netUnrealizedPnL="not-a-number")],
        ]
        for rows in invalid_rows:
            with self.subTest(rows=repr(rows)):
                self.assertIsNone(scale_unrealized_pnl(rows, 2))
        self.assertIsNone(scale_unrealized_pnl([SimpleNamespace(netUnrealizedPnL=100)], None))

    def test_missing_or_invalid_balance_fields_remain_unknown(self):
        for balance, digits in (
            (None, 2), (100, None), ("bad", 2), (100, -1), (100, 13),
            (float("nan"), 2), (float("inf"), 2), (100, 2.5), (100, True),
        ):
            with self.subTest(balance=balance, digits=digits):
                self.assertIsNone(scale_balance(balance, digits))


if __name__ == "__main__":
    unittest.main()
