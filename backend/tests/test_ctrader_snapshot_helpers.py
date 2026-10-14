import unittest

from app.ctrader_snapshot_helpers import normalize_trade_side, scale_balance


class CTraderSnapshotHelpersTests(unittest.TestCase):
    def test_normalizes_known_trade_sides(self):
        self.assertEqual(normalize_trade_side(1), "BUY")
        self.assertEqual(normalize_trade_side(2), "SELL")

    def test_unknown_or_invalid_trade_side_fails_closed(self):
        for value in (None, 0, 3, "bad", object()):
            with self.subTest(value=repr(value)):
                self.assertEqual(normalize_trade_side(value), "UNKNOWN")

    def test_scales_balance_with_money_digits(self):
        self.assertEqual(scale_balance(123456, 2), 1234.56)
        self.assertEqual(scale_balance(123456, 0), 123456.0)

    def test_missing_or_invalid_balance_fields_remain_unknown(self):
        for balance, digits in ((None, 2), (100, None), ("bad", 2), (100, -1), (100, 13)):
            with self.subTest(balance=balance, digits=digits):
                self.assertIsNone(scale_balance(balance, digits))


if __name__ == "__main__":
    unittest.main()
