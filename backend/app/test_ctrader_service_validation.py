"""Regression tests for strict cTrader identifier and volume validation."""
import unittest
from decimal import Decimal
from fractions import Fraction

from backend.app.ctrader_service import _positive_int


class PositiveIntegerTests(unittest.TestCase):
    def test_accepts_integral_decimal(self):
        self.assertEqual(_positive_int(Decimal("42"), "account_id"), 42)

    def test_rejects_fractional_decimal_instead_of_truncating(self):
        with self.assertRaises(ValueError):
            _positive_int(Decimal("42.5"), "account_id")

    def test_rejects_fractional_rational_instead_of_truncating(self):
        with self.assertRaises(ValueError):
            _positive_int(Fraction(5, 2), "volume")

    def test_rejects_boolean(self):
        with self.assertRaises(ValueError):
            _positive_int(True, "account_id")

    def test_rejects_non_positive_integer(self):
        with self.assertRaises(ValueError):
            _positive_int(0, "account_id")


if __name__ == "__main__":
    unittest.main()
