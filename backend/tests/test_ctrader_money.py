import unittest

from app.ctrader_money import decode_money_value, validate_money_digits


class CTraderMoneyTests(unittest.TestCase):
    def test_decodes_money_using_broker_precision(self):
        self.assertEqual(decode_money_value(12345, 2), 123.45)
        self.assertEqual(decode_money_value(-25, 0), -25.0)

    def test_uses_explicit_fallback_when_precision_is_missing(self):
        self.assertEqual(validate_money_digits(None, fallback=3), 3)
        self.assertEqual(decode_money_value(1250, 3), 1.25)

    def test_rejects_invalid_precision(self):
        for digits in (None, True, False, -1, 13, 2.5, "2"):
            with self.subTest(digits=digits):
                with self.assertRaisesRegex(ValueError, "moneyDigits"):
                    validate_money_digits(digits)

    def test_rejects_malformed_or_non_finite_money(self):
        for value in (True, float("nan"), float("inf"), -float("inf"), "bad", object()):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "monetary value"):
                    decode_money_value(value, 2)


if __name__ == "__main__":
    unittest.main()
