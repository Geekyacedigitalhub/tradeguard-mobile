import unittest

from app.ctrader_protection_validation import validate_positive_identifier, validate_protection_request


class CTraderProtectionValidationTests(unittest.TestCase):
    def test_rejects_invalid_position_id(self):
        for value in (0, -1, True, False, 1.5, "12", None):
            with self.subTest(position_id=value):
                with self.assertRaises(ValueError):
                    validate_protection_request(value, stop_loss=1.2)

    def test_rejects_invalid_stop_loss(self):
        for value in (0, -1, True, False, float("nan"), float("inf"), -float("inf"), "1.2", object()):
            with self.subTest(stop_loss=repr(value)):
                with self.assertRaises(ValueError):
                    validate_protection_request(12, stop_loss=value)

    def test_rejects_invalid_take_profit(self):
        for value in (0, -1, True, float("nan"), float("inf"), "1.2"):
            with self.subTest(take_profit=repr(value)):
                with self.assertRaises(ValueError):
                    validate_protection_request(12, take_profit=value)

    def test_requires_at_least_one_protection_price(self):
        with self.assertRaises(ValueError):
            validate_protection_request(12)

    def test_accepts_stop_loss_only(self):
        self.assertEqual(validate_protection_request(12, stop_loss=1.234), (12, 1.234, None))

    def test_accepts_take_profit_only(self):
        self.assertEqual(validate_protection_request(12, take_profit=2), (12, None, 2.0))

    def test_accepts_both_prices(self):
        self.assertEqual(validate_protection_request(12, stop_loss=1.1, take_profit=1.3), (12, 1.1, 1.3))

    def test_positive_identifier_requires_integer_without_coercion(self):
        self.assertEqual(validate_positive_identifier(12, "account id"), 12)
        for value in (0, -1, True, False, 1.0, "12", None):
            with self.subTest(identifier=value):
                with self.assertRaises(ValueError):
                    validate_positive_identifier(value, "account id")


if __name__ == "__main__":
    unittest.main()
