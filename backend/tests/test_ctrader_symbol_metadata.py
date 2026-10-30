import unittest
from types import SimpleNamespace

from app.ctrader_service import CTraderManager


class CTraderSymbolMetadataTests(unittest.IsolatedAsyncioTestCase):
    async def _metadata(self, *, base_asset_id=1, quote_asset_id=2):
        # This SDK's SymbolsList carries identity only (id, name, enabled,
        # base/quote asset ids); product fields come from SymbolById. The fake
        # must mirror that split or the test is proving nothing about the
        # real wire messages.
        manager = CTraderManager()

        def _normalized(value):
            # Mirror the real fetch normalization exactly: malformed protocol
            # identifiers stay unavailable instead of being coerced.
            return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None

        async def fake_fetch_catalog(account_id, environment):
            return [
                {
                    "symbol_id": 42,
                    "symbol_name": "EURUSD",
                    "enabled": True,
                    "base_asset_id": _normalized(base_asset_id),
                    "quote_asset_id": _normalized(quote_asset_id),
                }
            ]

        async def fake_fetch_product(account_id, symbol_id, environment):
            return {
                "symbol_id": symbol_id,
                "digits": 5,
                "lot_size": 100000,
                "min_volume": 100,
                "max_volume": 1000000,
                "step_volume": 100,
                "pip_position": 4,
            }

        manager._fetch_symbol_catalog = fake_fetch_catalog
        manager._fetch_symbol_product = fake_fetch_product
        return await manager.symbol_volume_units(123, 42)

    async def test_exposes_broker_asset_ids_but_does_not_claim_contract_verification(self):
        result = await self._metadata()
        self.assertEqual(result["base_asset_id"], 1)
        self.assertEqual(result["quote_asset_id"], 2)
        self.assertIsNone(result["instrument_type"])
        self.assertIsNone(result["contract_model"])
        self.assertFalse(result["risk_sizing_verified"])
        self.assertEqual(result["digits"], 5)
        self.assertEqual(result["min_volume"], 100)

    async def test_missing_or_malformed_asset_ids_remain_unavailable(self):
        result = await self._metadata(base_asset_id=True, quote_asset_id="2")
        self.assertIsNone(result["base_asset_id"])
        self.assertIsNone(result["quote_asset_id"])
        self.assertFalse(result["risk_sizing_verified"])


if __name__ == "__main__":
    unittest.main()
