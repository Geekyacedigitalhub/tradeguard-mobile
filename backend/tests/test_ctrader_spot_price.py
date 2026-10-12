import unittest

from app.ctrader_service import decode_spot_price


class CTraderSpotPriceTests(unittest.TestCase):
    def test_scales_forex_prices_by_symbol_digits(self):
        self.assertEqual(decode_spot_price(108123, 3), 108.123)
        self.assertEqual(decode_spot_price(149876, 3), 149.876)
        self.assertEqual(decode_spot_price(10812345, 5), 108.12345)
        self.assertEqual(decode_spot_price(52345, 2), 523.45)

    def test_rejects_missing_or_invalid_prices_and_precision(self):
        for raw, digits in (
            (None, 5),
            (0, 5),
            (-10, 5),
            (float("nan"), 5),
            (float("inf"), 5),
            (100, None),
            (100, -1),
            (100, 13),
            (100, 2.5),
            ("108123", 3),
            (108123.0, 3),
            (108123, "3"),
            (True, 5),
            (100, True),
        ):
            with self.subTest(raw=raw, digits=digits):
                self.assertIsNone(decode_spot_price(raw, digits))


if __name__ == "__main__":
    unittest.main()
