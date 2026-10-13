import unittest

from fastapi import HTTPException

from app.ctrader_oauth_api import _validated_preflight_symbol_id


class CTraderPreflightIdentifierTests(unittest.TestCase):
    def test_accepts_largest_signed_protocol_symbol_id(self):
        maximum = (1 << 63) - 1
        self.assertEqual(_validated_preflight_symbol_id(maximum), maximum)

    def test_rejects_zero_and_negative_symbol_ids(self):
        for value in (0, -1):
            with self.subTest(value=value):
                with self.assertRaises(HTTPException) as caught:
                    _validated_preflight_symbol_id(value)
                self.assertEqual(caught.exception.status_code, 400)

    def test_rejects_symbol_ids_above_signed_protocol_range(self):
        for value in ((1 << 63), 10 ** 100):
            with self.subTest(value=value):
                with self.assertRaises(HTTPException) as caught:
                    _validated_preflight_symbol_id(value)
                self.assertEqual(caught.exception.status_code, 400)
                self.assertIn("protocol integer", caught.exception.detail)


if __name__ == "__main__":
    unittest.main()
