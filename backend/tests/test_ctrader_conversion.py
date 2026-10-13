import unittest

from app.ctrader_conversion import convert_asset_amount, normalize_conversion_symbols


NOW = 1_800_000_000_000


class CTraderAssetConversionTests(unittest.TestCase):
    def setUp(self):
        self.symbols = [
            {"symbol_id": 11, "symbol_name": "EURUSD", "base_asset_id": 1, "quote_asset_id": 2},
            {"symbol_id": 12, "symbol_name": "USDJPY", "base_asset_id": 2, "quote_asset_id": 3},
        ]
        self.quotes = {
            11: {"bid": 1.10, "ask": 1.11, "timestamp_ms": NOW - 1000},
            12: {"bid": 150.0, "ask": 150.2, "timestamp_ms": NOW - 1000},
        }

    def convert(self, amount=10, source=1, target=3, **kwargs):
        args = {
            "conversion_symbols": self.symbols,
            "quotes_by_symbol_id": self.quotes,
            "now_timestamp_ms": NOW,
        }
        args.update(kwargs)
        return convert_asset_amount(amount, source, target, **args)

    def test_normalizes_valid_broker_conversion_metadata(self):
        raw = [{"symbol_id": 11, "symbol_name": " EURUSD ",
                "base_asset_id": 1, "quote_asset_id": 2}]
        self.assertEqual(normalize_conversion_symbols(raw), [{
            "symbol_id": 11, "symbol_name": "EURUSD",
            "base_asset_id": 1, "quote_asset_id": 2,
        }])

    def test_rejects_malformed_or_ambiguous_broker_metadata(self):
        invalid_cases = [
            [{"symbol_id": "11", "symbol_name": "EURUSD", "base_asset_id": 1, "quote_asset_id": 2}],
            [{"symbol_id": True, "symbol_name": "EURUSD", "base_asset_id": 1, "quote_asset_id": 2}],
            [{"symbol_id": 11, "symbol_name": "EURUSD", "base_asset_id": 1, "quote_asset_id": 1}],
            [{"symbol_id": 11, "symbol_name": "", "base_asset_id": 1, "quote_asset_id": 2}],
            [
                {"symbol_id": 11, "symbol_name": "EURUSD", "base_asset_id": 1, "quote_asset_id": 2},
                {"symbol_id": 11, "symbol_name": "EURGBP", "base_asset_id": 1, "quote_asset_id": 3},
            ],
            [],
        ]
        for metadata in invalid_cases:
            with self.subTest(metadata=metadata):
                with self.assertRaises(ValueError):
                    normalize_conversion_symbols(metadata)

    def test_converts_along_two_symbol_path_using_executable_sides(self):
        result = self.convert()
        self.assertAlmostEqual(result["rate"], 1.10 * 150.0)
        self.assertAlmostEqual(result["amount"], 1650.0)
        self.assertEqual([x["symbol_id"] for x in result["path"]], [11, 12])
        self.assertEqual([x["price_side"] for x in result["path"]], ["bid", "bid"])
        self.assertTrue(result["conversion_verified"])
        self.assertFalse(result["risk_sizing_verified"])

    def test_converter_rejects_duplicate_symbol_ids_without_normalization(self):
        duplicate_symbols = self.symbols + [
            {"symbol_id": 11, "symbol_name": "EURGBP", "base_asset_id": 1, "quote_asset_id": 3},
        ]
        with self.assertRaisesRegex(ValueError, "duplicate symbol IDs"):
            self.convert(conversion_symbols=duplicate_symbols)

    def test_bad_quote_on_unused_branch_does_not_hide_valid_path(self):
        symbols = self.symbols + [
            {"symbol_id": 13, "symbol_name": "EURGBP", "base_asset_id": 1, "quote_asset_id": 4},
            {"symbol_id": 14, "symbol_name": "GBPJPY", "base_asset_id": 4, "quote_asset_id": 3},
        ]
        quotes = {
            11: {"bid": 0, "ask": 1.11, "timestamp_ms": NOW - 1000},
            12: {"bid": 150.0, "ask": 150.2, "timestamp_ms": NOW - 1000},
            13: {"bid": 0.8, "ask": 0.81, "timestamp_ms": NOW - 1000},
            14: {"bid": 180.0, "ask": 180.2, "timestamp_ms": NOW - 1000},
        }
        result = self.convert(conversion_symbols=symbols, quotes_by_symbol_id=quotes)
        self.assertEqual([edge["symbol_id"] for edge in result["path"]], [13, 14])
        self.assertAlmostEqual(result["amount"], 10 * 0.8 * 180.0)

    def test_quote_to_base_conversion_divides_by_ask(self):
        result = self.convert(amount=111, source=2, target=1)
        self.assertAlmostEqual(result["amount"], 100.0)
        self.assertEqual(result["path"][0]["price_side"], "ask")

    def test_same_asset_is_identity_but_not_trade_risk_approval(self):
        result = self.convert(amount=25, source=2, target=2)
        self.assertEqual(result["rate"], 1.0)
        self.assertEqual(result["amount"], 25.0)
        self.assertTrue(result["conversion_verified"])
        self.assertFalse(result["risk_sizing_verified"])

    def test_missing_quote_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "no fully quoted, fresh broker conversion path"):
            self.convert(quotes_by_symbol_id={})

    def test_stale_future_and_malformed_quotes_fail_closed(self):
        cases = [
            {"bid": 1.1, "ask": 1.11, "timestamp_ms": NOW - 10_000},
            {"bid": 1.1, "ask": 1.11, "timestamp_ms": NOW + 1},
            {"bid": 0, "ask": 1.11, "timestamp_ms": NOW},
            {"bid": 1.2, "ask": 1.1, "timestamp_ms": NOW},
        ]
        for quote in cases:
            with self.subTest(quote=quote):
                with self.assertRaises(ValueError):
                    self.convert(quotes_by_symbol_id={11: quote, 12: self.quotes[12]})

    def test_disconnected_assets_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "no fully quoted, fresh broker conversion path"):
            self.convert(source=1, target=99)

    def test_invalid_amount_and_identifiers_fail_closed(self):
        for amount in (0, -1, float("nan"), float("inf"), True):
            with self.subTest(amount=amount):
                with self.assertRaises(ValueError):
                    self.convert(amount=amount)
        with self.assertRaises(ValueError):
            self.convert(source=True)

    def test_missing_or_invalid_asset_metadata_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "identifiers"):
            self.convert(conversion_symbols=[{"symbol_id": 11, "base_asset_id": 1, "quote_asset_id": 0}])


if __name__ == "__main__":
    unittest.main()
