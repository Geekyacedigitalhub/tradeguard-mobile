"""Integration tests for the cTrader live-quote sizing diagnostic.

These tests mock the broker boundary: they validate TradeGuard's orchestration
and fail-closed behavior, not a live cTrader connection or broker execution.
"""
import time
import unittest
from unittest.mock import AsyncMock

from app.ctrader_service import CTraderManager


class CTraderSizingIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.manager = CTraderManager()
        self.metadata = {
            "symbol_id": 1,
            "symbol_name": "EURUSD",
            "digits": 5,
            "pip_position": 4,
            "base_asset_id": 1,
            "quote_asset_id": 2,
            "lot_size": 100000,
            "min_volume": 1000,
            "max_volume": 10000000,
            "step_volume": 1000,
            "volume_is_raw_protocol_units": True,
            "risk_sizing_verified": False,
        }
        self.manager.symbol_volume_units = AsyncMock(return_value=dict(self.metadata))
        self.manager.deposit_asset_id = AsyncMock(return_value=3)
        self.manager.fresh_conversion_quotes = AsyncMock(return_value={
            "conversion_symbols": [
                {
                    "symbol_id": 20,
                    "base_asset_id": 2,
                    "quote_asset_id": 3,
                    "symbol_name": "USDGBP",
                }
            ],
            "quotes_by_symbol_id": {
                20: {"bid": 0.8, "ask": 0.81, "timestamp": time.time()}
            },
            "observed_at": time.time(),
            "max_quote_age_seconds": 15.0,
        })

    async def test_sizes_with_fresh_account_currency_conversion(self):
        result = await self.manager.size_fx_order_from_live_quotes(
            user_id="user-1",
            account_id=123,
            access_token="test-token",
            symbol_id=1,
            risk_amount=100,
            stop_distance=0.01,
            environment="demo",
        )
        self.assertAlmostEqual(result["quote_to_deposit_conversion_rate"], 0.8)
        self.assertEqual(result["deposit_asset_id"], 3)
        self.assertEqual(result["broker_volume"], 1250000)
        self.assertLessEqual(result["estimated_loss_at_stop"], 100)
        self.assertTrue(result["broker_volume_verified"])
        self.assertFalse(result["execution_ready"])
        self.assertEqual(result["sizing_scope"], "standard_six_letter_fx_pair")

    async def test_rejects_live_account_sizing(self):
        with self.assertRaisesRegex(ValueError, "restricted to cTrader demo"):
            await self.manager.size_fx_order_from_live_quotes(
                user_id="user-1", account_id=123, access_token="test-token",
                symbol_id=1, risk_amount=100, stop_distance=0.01,
                environment="live",
            )
        self.manager.symbol_volume_units.assert_not_awaited()

    async def test_rejects_missing_asset_metadata(self):
        self.manager.symbol_volume_units.return_value = {
            **self.metadata, "base_asset_id": 0,
        }
        with self.assertRaisesRegex(ValueError, "base/quote asset metadata is missing"):
            await self.manager.size_fx_order_from_live_quotes(
                user_id="user-1", account_id=123, access_token="test-token",
                symbol_id=1, risk_amount=100, stop_distance=0.01,
            )

    async def test_rejects_non_standard_symbol_instead_of_guessing_contract(self):
        self.manager.symbol_volume_units.return_value = {
            **self.metadata, "symbol_name": "XAUUSD",
        }
        with self.assertRaisesRegex(ValueError, "standard six-letter FX pairs only"):
            await self.manager.size_fx_order_from_live_quotes(
                user_id="user-1", account_id=123, access_token="test-token",
                symbol_id=1, risk_amount=100, stop_distance=0.01,
            )

    async def test_rejects_stale_conversion_quotes(self):
        self.manager.fresh_conversion_quotes.return_value = {
            "conversion_symbols": [
                {"symbol_id": 20, "base_asset_id": 2, "quote_asset_id": 3}
            ],
            "quotes_by_symbol_id": {
                20: {"bid": 0.8, "ask": 0.81, "timestamp": time.time() - 60}
            },
            "observed_at": time.time() - 60,
            "max_quote_age_seconds": 15.0,
        }
        with self.assertRaisesRegex(ValueError, "stale or from the future"):
            await self.manager.size_fx_order_from_live_quotes(
                user_id="user-1", account_id=123, access_token="test-token",
                symbol_id=1, risk_amount=100, stop_distance=0.01,
            )

    async def test_rejects_risk_below_broker_minimum_volume(self):
        with self.assertRaisesRegex(ValueError, "below the symbol's minimum"):
            await self.manager.size_fx_order_from_live_quotes(
                user_id="user-1", account_id=123, access_token="test-token",
                symbol_id=1, risk_amount=0.00001, stop_distance=0.01,
            )

    async def test_same_deposit_and_quote_asset_uses_unit_conversion(self):
        self.manager.deposit_asset_id = AsyncMock(return_value=2)
        self.manager.fresh_conversion_quotes.return_value = {
            "conversion_symbols": [],
            "quotes_by_symbol_id": {},
            "observed_at": time.time(),
            "max_quote_age_seconds": 15.0,
        }
        result = await self.manager.size_fx_order_from_live_quotes(
            user_id="user-1", account_id=123, access_token="test-token",
            symbol_id=1, risk_amount=100, stop_distance=0.01,
        )
        self.assertEqual(result["quote_to_deposit_conversion_rate"], 1.0)
        self.assertTrue(result["broker_volume_verified"])
        self.assertFalse(result["execution_ready"])


    async def test_symbol_volume_metadata_combines_light_and_full_records(self):
        from types import SimpleNamespace

        light = SimpleNamespace(
            symbolId=1, symbolName="EUR/USD", baseAssetId=11, quoteAssetId=22
        )
        full = SimpleNamespace(
            symbolId=1, digits=5, pipPosition=4, lotSize=100000,
            minVolume=1000, maxVolume=5000000, stepVolume=1000,
        )
        self.manager.symbols = AsyncMock(return_value=SimpleNamespace(symbol=[light]))
        self.manager.symbol_by_id = AsyncMock(return_value=full)

        result = await self.manager.symbol_volume_units(123, 1, "demo")

        self.assertEqual(result["symbol_name"], "EUR/USD")
        self.assertEqual(result["base_asset_id"], 11)
        self.assertEqual(result["quote_asset_id"], 22)
        self.assertEqual(result["lot_size"], 100000)
        self.assertEqual(result["min_volume"], 1000)
        self.assertEqual(result["max_volume"], 5000000)
        self.assertEqual(result["step_volume"], 1000)
        self.assertFalse(result["risk_sizing_verified"])
        self.manager.symbol_by_id.assert_awaited_once_with(123, 1, "demo")

    async def test_symbol_volume_metadata_fails_when_full_record_is_missing(self):
        from types import SimpleNamespace

        light = SimpleNamespace(
            symbolId=1, symbolName="EURUSD", baseAssetId=11, quoteAssetId=22
        )
        self.manager.symbols = AsyncMock(return_value=SimpleNamespace(symbol=[light]))
        self.manager.symbol_by_id = AsyncMock(
            side_effect=RuntimeError("cTrader full metadata is unavailable")
        )

        with self.assertRaisesRegex(RuntimeError, "full metadata is unavailable"):
            await self.manager.symbol_volume_units(123, 1, "demo")



if __name__ == "__main__":
    unittest.main()
