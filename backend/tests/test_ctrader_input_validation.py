import unittest

from app.ctrader_service import _positive_int, _positive_price
from app.ctrader_tokens import _token_expiry_seconds


class CTraderInputValidationTests(unittest.TestCase):
    def test_positive_int_accepts_valid_ids_and_volumes(self):
        for value, expected in ((1, 1), (25, 25), (3.0, 3), ("42", 42), ("+7", 7)):
            with self.subTest(value=value):
                self.assertEqual(_positive_int(value, "field"), expected)

    def test_positive_int_rejects_invalid_values(self):
        for value in (None, True, False, 0, -1, 1.5, float("nan"), float("inf"), "", "  ", "1.0", "1.2", "abc"):
            with self.subTest(value=repr(value)):
                with self.assertRaises(ValueError):
                    _positive_int(value, "field")

    def test_positive_price_accepts_finite_positive_values(self):
        self.assertEqual(_positive_price(1, "price"), 1.0)
        self.assertEqual(_positive_price("1.25", "price"), 1.25)

    def test_positive_price_rejects_invalid_values(self):
        for value in (None, True, False, 0, -1, float("nan"), float("inf"), float("-inf"), "bad"):
            with self.subTest(value=repr(value)):
                with self.assertRaises(ValueError):
                    _positive_price(value, "price")

    def test_token_expiry_accepts_positive_integer_seconds(self):
        for value, expected in ((1, 1), (3600, 3600), ("2628000", 2628000), (60.0, 60)):
            with self.subTest(value=value):
                self.assertEqual(_token_expiry_seconds(value), expected)

    def test_token_expiry_rejects_nonpositive_or_malformed_values(self):
        invalid_values = (
            None, True, False, 0, -1, 1.5, "1.5", "", "invalid",
            float("nan"), float("inf"), float("-inf"),
        )
        for value in invalid_values:
            with self.subTest(value=repr(value)):
                with self.assertRaises(RuntimeError):
                    _token_expiry_seconds(value)


    def test_snapshot_trade_side_normalization(self):
        from app.ctrader_snapshot_helpers import normalize_trade_side

        for raw, expected in ((1, "BUY"), (2, "SELL"), ("1", "BUY"), ("2", "SELL")):
            with self.subTest(raw=raw):
                self.assertEqual(normalize_trade_side(raw), expected)
        for raw in (None, True, False, 0, 3, 1.5, "1.0", "bad"):
            with self.subTest(raw=raw):
                self.assertEqual(normalize_trade_side(raw), "UNKNOWN")

    def test_snapshot_balance_scaling_rejects_invalid_values(self):
        from app.ctrader_snapshot_helpers import scale_balance

        self.assertEqual(scale_balance(12345, 2), 123.45)
        self.assertIsNone(scale_balance(None, 2))
        self.assertIsNone(scale_balance(12345, None))
        for balance, digits in ((float("nan"), 2), (float("inf"), 2), (100, -1), (100, 13), (100, True), (100, 1.5)):
            with self.subTest(balance=balance, digits=digits):
                self.assertIsNone(scale_balance(balance, digits))


if __name__ == "__main__":
    unittest.main()
