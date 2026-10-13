import unittest
from types import SimpleNamespace
from app.ctrader_symbol_catalog import normalize_symbol_catalog


class CTraderSymbolCatalogTests(unittest.TestCase):
    def test_keeps_contract_type_unverified(self):
        item = SimpleNamespace(symbolId=42, symbolName="EURUSD", digits=5, lotSize=100000,
            baseAssetId=1, quoteAssetId=2, minVolume=100, maxVolume=1000000, stepVolume=100)
        row = normalize_symbol_catalog([item])[0]
        self.assertEqual(row["base_asset_id"], 1)
        self.assertTrue(row["volume_constraints_valid"])
        self.assertIsNone(row["instrument_type"])
        self.assertIsNone(row["contract_model"])
        self.assertFalse(row["risk_sizing_verified"])
        self.assertTrue(row["requires_broker_specific_contract_verification"])

    def test_bad_asset_ids_are_not_coerced(self):
        item = SimpleNamespace(symbolId=42, symbolName="EURUSD", digits=5, lotSize=100000,
            baseAssetId=True, quoteAssetId="2", minVolume=100, maxVolume=1000000, stepVolume=100)
        row = normalize_symbol_catalog([item])[0]
        self.assertIsNone(row["base_asset_id"])
        self.assertIsNone(row["quote_asset_id"])

    def test_out_of_range_protocol_ids_and_volumes_are_not_accepted(self):
        item = SimpleNamespace(
            symbolId=1 << 63, symbolName="EURUSD", digits=5, lotSize=100000,
            baseAssetId=1 << 63, quoteAssetId=2,
            minVolume=100, maxVolume=1 << 63, stepVolume=100,
        )
        self.assertEqual(normalize_symbol_catalog([item]), [])

        item.symbolId = 42
        row = normalize_symbol_catalog([item])[0]
        self.assertIsNone(row["base_asset_id"])
        self.assertIsNone(row["max_volume"])
        self.assertFalse(row["volume_constraints_valid"])

    def test_search_filters_names(self):
        items = [
            SimpleNamespace(symbolId=1, symbolName="EURUSD", digits=5, lotSize=100000,
                baseAssetId=1, quoteAssetId=2, minVolume=100, maxVolume=1000, stepVolume=100),
            SimpleNamespace(symbolId=2, symbolName="GBPJPY", digits=3, lotSize=100000,
                baseAssetId=3, quoteAssetId=4, minVolume=100, maxVolume=1000, stepVolume=100),
        ]
        self.assertEqual([x["symbol_name"] for x in normalize_symbol_catalog(items, query="gbp")], ["GBPJPY"])


if __name__ == "__main__":
    unittest.main()
