import unittest
import time

from app.ctrader_service import decode_spot_price, is_fill_execution, CTraderManager, _Session


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

    def test_conversion_quote_snapshot_requires_fresh_cached_quotes(self):
        manager = CTraderManager()
        now_ms = int(time.time() * 1000)
        symbols = [
            {"symbol_id": 11, "symbol_name": "EURUSD", "base_asset_id": 1, "quote_asset_id": 2},
            {"symbol_id": 12, "symbol_name": "USDJPY", "base_asset_id": 2, "quote_asset_id": 3},
        ]
        session = _Session(client=None, environment="demo")
        session.authorized_accounts.add(123)
        session.latest_spots[(123, 11)] = {
            "bid": 1.10, "ask": 1.11, "timestamp": now_ms - 100,
        }
        session.latest_spots[(123, 12)] = {
            "bid": 150.0, "ask": 150.2, "timestamp": now_ms - 100,
        }
        manager._sessions["demo"] = session
        snapshot = manager.conversion_quote_snapshot(123, symbols, "demo")
        self.assertEqual(set(snapshot["quotes_by_symbol_id"]), {11, 12})
        self.assertFalse(snapshot["risk_sizing_verified"])

    def test_conversion_quote_snapshot_fails_closed_if_quote_missing_or_stale(self):
        manager = CTraderManager()
        now_ms = int(time.time() * 1000)
        symbols = [
            {"symbol_id": 11, "symbol_name": "EURUSD", "base_asset_id": 1, "quote_asset_id": 2},
            {"symbol_id": 12, "symbol_name": "USDJPY", "base_asset_id": 2, "quote_asset_id": 3},
        ]
        session = _Session(client=None, environment="demo")
        session.authorized_accounts.add(123)
        session.latest_spots[(123, 11)] = {
            "bid": 1.10, "ask": 1.11, "timestamp": now_ms - 100,
        }
        manager._sessions["demo"] = session
        with self.assertRaisesRegex(RuntimeError, "not safe to use"):
            manager.conversion_quote_snapshot(123, symbols, "demo")
        session.latest_spots[(123, 12)] = {
            "bid": 150.0, "ask": 150.2, "timestamp": now_ms - 6000,
        }
        with self.assertRaisesRegex(RuntimeError, "not safe to use"):
            manager.conversion_quote_snapshot(123, symbols, "demo")

    def test_only_full_or_partial_fill_counts_as_fill_evidence(self):
        self.assertTrue(is_fill_execution(3, filled_type=3, partial_fill_type=2))
        self.assertTrue(is_fill_execution(2, filled_type=3, partial_fill_type=2))
        self.assertFalse(is_fill_execution(1, filled_type=3, partial_fill_type=2))
        self.assertFalse(is_fill_execution(4, filled_type=3, partial_fill_type=None))
        self.assertFalse(is_fill_execution(None, filled_type=3, partial_fill_type=2))


if __name__ == "__main__":
    unittest.main()
