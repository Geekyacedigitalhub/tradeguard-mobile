import unittest

from app.ctrader_service import _positive_int, _positive_price


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


if __name__ == "__main__":
    unittest.main()
