import unittest
from types import SimpleNamespace

from app.ctrader_service import CTraderManager


class CTraderSymbolMetadataTests(unittest.IsolatedAsyncioTestCase):
    async def _metadata(self, *, base_asset_id=1, quote_asset_id=2):
        manager = CTraderManager()
        symbol = SimpleNamespace(
            symbolId=42,
            symbolName="EURUSD",
            digits=5,
            lotSize=100000,
            minVolume=100,
            maxVolume=1000000,
            stepVolume=100,
            baseAssetId=base_asset_id,
            quoteAssetId=quote_asset_id,
        )

        async def fake_symbols(account_id, environment="demo"):
            return SimpleNamespace(symbol=[symbol])

        manager.symbols = fake_symbols
        return await manager.symbol_volume_units(123, 42)

    async def test_exposes_broker_asset_ids_but_does_not_claim_contract_verification(self):
        result = await self._metadata()
        self.assertEqual(result["base_asset_id"], 1)
        self.assertEqual(result["quote_asset_id"], 2)
        self.assertIsNone(result["instrument_type"])
        self.assertIsNone(result["contract_model"])
        self.assertFalse(result["risk_sizing_verified"])

    async def test_missing_or_malformed_asset_ids_remain_unavailable(self):
        result = await self._metadata(base_asset_id=True, quote_asset_id="2")
        self.assertIsNone(result["base_asset_id"])
        self.assertIsNone(result["quote_asset_id"])
        self.assertFalse(result["risk_sizing_verified"])


if __name__ == "__main__":
    unittest.main()
