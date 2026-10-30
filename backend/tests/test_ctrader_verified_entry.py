import math
import time
import unittest
from types import SimpleNamespace

from app.ctrader_verified_entry import (
    build_verified_sizing_evidence,
    entry_client_order_id,
    find_symbol_in_catalog,
    is_verified_currency_asset,
)
from app.ctrader_execution_guard import entry_block_reason


def _now_ms():
    return int(time.time() * 1000)


class FakeManager:
    """Mirrors the CTraderManager surface used by verified-entry sizing."""

    def __init__(self, *, deposit_asset_id=2, trader=None):
        self.account_id = 123
        self.trader_obj = trader or SimpleNamespace(depositAssetId=deposit_asset_id, traderLogin=49093168)
        self.catalog = [
            {"symbol_id": 42, "symbol_name": "EURUSD", "enabled": True, "base_asset_id": 1, "quote_asset_id": 2},
            {"symbol_id": 77, "symbol_name": "XAUUSD", "enabled": True, "base_asset_id": 5, "quote_asset_id": 2},
        ]
        self.products = {
            42: {"symbol_id": 42, "digits": 5, "lot_size": 100000, "min_volume": 100,
                 "max_volume": 1000000, "step_volume": 100, "pip_position": 4},
            77: {"symbol_id": 77, "digits": 2, "lot_size": 100, "min_volume": 100,
                 "max_volume": 1000000, "step_volume": 100, "pip_position": 2},
        }
        self.assets = {1: "EUR", 2: "USD", 3: "EUR", 5: "XAU"}
        self.conversion_symbols = []
        self.quote_snapshot = None
        self.reconcile_positions = []
        self.orders = []

    async def trader(self, account_id, environment="demo"):
        return self.trader_obj

    async def symbol_catalog(self, account_id, environment="demo"):
        return self.catalog

    async def symbol_product(self, account_id, symbol_id, environment="demo"):
        if symbol_id not in self.products:
            raise RuntimeError(f"cTrader symbol id {symbol_id} is not available on this account")
        return self.products[symbol_id]

    async def asset_catalog(self, account_id, environment="demo"):
        return self.assets

    async def symbols_for_conversion(self, account_id, first_asset_id, last_asset_id, environment="demo"):
        if first_asset_id == last_asset_id:
            return {"symbols": [], "same_asset": True}
        return {"symbols": self.conversion_symbols, "same_asset": False}

    async def subscribe_conversion_quotes(self, user_id, account_id, symbols, access_token, environment="demo", *, timeout=20.0):
        if self.quote_snapshot is None:
            raise RuntimeError("no fresh quotes available")
        return self.quote_snapshot

    async def reconcile(self, account_id, environment="demo"):
        return SimpleNamespace(position=self.reconcile_positions)

    async def new_market_order(self, account_id, symbol_id, side, volume, environment="demo", **kwargs):
        self.orders.append({"account_id": account_id, "symbol_id": symbol_id, "side": side,
                            "volume": volume, "kwargs": kwargs})
        return SimpleNamespace(status="ok")


class CurrencyAssetTests(unittest.TestCase):
    def test_accepts_audited_currency_codes(self):
        for code in ("USD", "EUR", "GBP", "JPY", "ZAR"):
            self.assertTrue(is_verified_currency_asset(code))

    def test_metals_and_indices_are_not_currencies(self):
        for name in ("XAG", "XAU"):
            self.assertFalse(is_verified_currency_asset(name))

    def test_rejects_non_currencies_and_garbage(self):
        for name in ("XAU", "GOLD", "NAS100", "BTC", "USDXX", "us1", "", "usd", "USD ", "USDX", None, 123):
            self.assertFalse(is_verified_currency_asset(name))


class CatalogMatchTests(unittest.TestCase):
    def test_exact_unambiguous_enabled_match(self):
        manager = FakeManager()
        row = find_symbol_in_catalog(manager.catalog, "eurusd")
        self.assertEqual(row["symbol_id"], 42)

    def test_disabled_or_duplicate_symbols_do_not_match(self):
        catalog = [
            {"symbol_id": 42, "symbol_name": "EURUSD", "enabled": False, "base_asset_id": 1, "quote_asset_id": 2},
        ]
        self.assertIsNone(find_symbol_in_catalog(catalog, "EURUSD"))
        catalog = [
            {"symbol_id": 42, "symbol_name": "EURUSD", "enabled": True, "base_asset_id": 1, "quote_asset_id": 2},
            {"symbol_id": 43, "symbol_name": "EURUSD", "enabled": True, "base_asset_id": 1, "quote_asset_id": 2},
        ]
        self.assertIsNone(find_symbol_in_catalog(catalog, "EURUSD"))


class VerifiedEntryEvidenceTests(unittest.IsolatedAsyncioTestCase):
    def _payload(self, **overrides):
        payload = {
            "symbol_name": "EURUSD",
            "trade_side": "BUY",
            "entry_price": 1.1000,
            "stop_price": 1.0900,
            "target_price": 1.1200,
            "risk_budget_account_currency": 10.0,
        }
        payload.update(overrides)
        return payload

    async def _evidence(self, manager, **payload):
        p = self._payload(**payload)
        return await build_verified_sizing_evidence(
            manager=manager,
            user_id="user-1",
            account_id=manager.account_id,
            environment="demo",
            symbol_name=p["symbol_name"],
            trade_side=p["trade_side"],
            entry_price=p["entry_price"],
            stop_price=p["stop_price"],
            target_price=p["target_price"],
            risk_budget_account_currency=p["risk_budget_account_currency"],
            access_token="token",
        )

    async def test_same_deposit_currency_evidence_passes_full_guard(self):
        manager = FakeManager(deposit_asset_id=2)  # account in USD; quote is USD
        evidence = await self._evidence(manager)
        self.assertTrue(evidence["risk_sizing_verified"])
        self.assertFalse(evidence["requires_broker_specific_contract_verification"])
        self.assertEqual(evidence["instrument_type"], "FX")
        self.assertEqual(evidence["contract_model"], "linear_fx_base_units")
        self.assertEqual(evidence["account_currency"], "USD")
        self.assertEqual(evidence["conversion_path_symbol_ids"], [])
        self.assertEqual(evidence["conversion_quote_timestamps_ms"], [])
        self.assertEqual(evidence["loss_per_price_unit_per_traded_unit"], 1.0)
        self.assertEqual(evidence["broker_volume"], 100000)  # 10 USD / 0.01 stop distance
        block = entry_block_reason(
            "demo", sizing_verified=True, sizing_evidence=evidence,
            expected_account_id=123, expected_symbol_id=42,
        )
        self.assertIsNone(block)

    async def test_cross_currency_conversion_evidence_passes_guard(self):
        # Account in EUR (3), quote in USD (2): conversion via USDEUR.
        manager = FakeManager(deposit_asset_id=3)
        manager.conversion_symbols = [
            {"symbol_id": 9, "symbol_name": "USDEUR", "base_asset_id": 2, "quote_asset_id": 3},
        ]
        fresh = _now_ms() - 1000
        manager.quote_snapshot = {
            "quotes_by_symbol_id": {9: {"bid": 0.92, "ask": 0.925, "timestamp_ms": fresh}},
            "snapshot_timestamp_ms": _now_ms(),
        }
        evidence = await self._evidence(manager)
        self.assertEqual(evidence["account_currency"], "EUR")
        self.assertEqual(evidence["conversion_path_symbol_ids"], [9])
        self.assertEqual(evidence["loss_per_price_unit_per_traded_unit"], 0.92)
        self.assertEqual(evidence["conversion_source_asset_id"], 2)
        self.assertEqual(evidence["conversion_target_asset_id"], 3)
        block = entry_block_reason(
            "demo", sizing_verified=True, sizing_evidence=evidence,
            expected_account_id=123, expected_symbol_id=42,
        )
        self.assertIsNone(block)

    async def test_non_fx_base_asset_stays_blocked(self):
        manager = FakeManager(deposit_asset_id=2)
        with self.assertRaisesRegex(RuntimeError, "not audited currency assets"):
            await self._evidence(manager, symbol_name="XAUUSD")

    async def test_unknown_broker_asset_stays_blocked(self):
        manager = FakeManager(deposit_asset_id=2)
        manager.catalog[0]["base_asset_id"] = 99  # asset 99 absent from asset catalog
        with self.assertRaisesRegex(RuntimeError, "asset metadata is incomplete"):
            await self._evidence(manager)

    async def test_non_currency_deposit_asset_stays_blocked(self):
        manager = FakeManager(deposit_asset_id=5)  # deposit "XAU"
        with self.assertRaisesRegex(RuntimeError, "deposit asset .* is not an audited currency asset"):
            await self._evidence(manager)

    async def test_stale_conversion_quote_stays_blocked(self):
        manager = FakeManager(deposit_asset_id=3)
        manager.conversion_symbols = [
            {"symbol_id": 9, "symbol_name": "USDEUR", "base_asset_id": 2, "quote_asset_id": 3},
        ]
        stale = _now_ms() - 10000
        manager.quote_snapshot = {
            "quotes_by_symbol_id": {9: {"bid": 0.92, "ask": 0.925, "timestamp_ms": stale}},
            "snapshot_timestamp_ms": _now_ms(),
        }
        with self.assertRaises(RuntimeError):
            await self._evidence(manager)

    async def test_missing_conversion_path_stays_blocked(self):
        manager = FakeManager(deposit_asset_id=3)
        manager.conversion_symbols = []
        with self.assertRaisesRegex(RuntimeError, "no conversion path"):
            await self._evidence(manager)

    async def test_missing_or_ambiguous_symbol_stays_blocked(self):
        manager = FakeManager(deposit_asset_id=2)
        with self.assertRaisesRegex(RuntimeError, "no exact, unambiguous, enabled broker match"):
            await self._evidence(manager, symbol_name="UNKNOWN")
        manager.catalog.append({"symbol_id": 44, "symbol_name": "EURUSD", "enabled": True,
                                "base_asset_id": 1, "quote_asset_id": 2})
        with self.assertRaisesRegex(RuntimeError, "no exact, unambiguous, enabled broker match"):
            await self._evidence(manager, symbol_name="EURUSD")

    async def test_stop_side_inconsistency_stays_blocked(self):
        manager = FakeManager(deposit_asset_id=2)
        with self.assertRaisesRegex(RuntimeError, "BUY entry must sit between"):
            await self._evidence(manager, stop_price=1.1100)
        with self.assertRaisesRegex(RuntimeError, "SELL entry must sit between"):
            await self._evidence(manager, trade_side="SELL", entry_price=1.1000, stop_price=1.0900, target_price=1.1200)

    async def test_budget_below_broker_minimum_stays_blocked(self):
        manager = FakeManager(deposit_asset_id=2)
        # Min volume 100 = 1 base unit -> 0.01 USD loss at the 0.01 stop
        # distance; a 0.005 USD budget cannot buy even the broker minimum.
        with self.assertRaisesRegex(RuntimeError, "broker minimum volume"):
            await self._evidence(manager, risk_budget_account_currency=0.005)

    async def test_live_environment_never_builds_evidence(self):
        manager = FakeManager(deposit_asset_id=2)
        p = self._payload()
        with self.assertRaisesRegex(RuntimeError, "Live accounts"):
            await build_verified_sizing_evidence(
                manager=manager, user_id="user-1", account_id=123, environment="live",
                symbol_name=p["symbol_name"], trade_side=p["trade_side"],
                entry_price=p["entry_price"], stop_price=p["stop_price"],
                target_price=p["target_price"], risk_budget_account_currency=p["risk_budget_account_currency"],
                access_token="token",
            )

    async def test_evidence_is_rejected_for_wrong_account_binding(self):
        manager = FakeManager(deposit_asset_id=2)
        evidence = await self._evidence(manager)
        block = entry_block_reason(
            "demo", sizing_verified=True, sizing_evidence=evidence,
            expected_account_id=999, expected_symbol_id=42,
        )
        self.assertIsNotNone(block)


class ClientOrderIdTests(unittest.TestCase):
    def test_stable_bounded_id(self):
        self.assertEqual(entry_client_order_id(7), "TG0000000007E")
        self.assertLessEqual(len(entry_client_order_id(123456789)), 36)

    def test_rejects_invalid_command_id(self):
        with self.assertRaises(ValueError):
            entry_client_order_id(0)
        with self.assertRaises(ValueError):
            entry_client_order_id("7")


class VerifiedEntryWorkerFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_confirmed_open_when_broker_reports_matching_position(self):
        from app.ctrader_worker import execute_verified_ctrader_entry

        manager = FakeManager(deposit_asset_id=2)
        from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATradeSide

        confirmed = SimpleNamespace(
            positionId=555,
            tradeData=SimpleNamespace(symbolId=42, volume=100000, tradeSide=int(ProtoOATradeSide.BUY)),
        )

        async def reconcile_after(account_id, environment="demo"):
            manager._call_count = getattr(manager, "_call_count", 0) + 1
            if manager._call_count >= 2:  # first = before, second = after
                manager.reconcile_positions = [confirmed]
            return SimpleNamespace(position=manager.reconcile_positions)

        manager.reconcile = reconcile_after
        result = await execute_verified_ctrader_entry(
            manager=manager, command_id=7, user_id="user-1", account_id=123,
            environment="demo",
            payload={"symbol": "EURUSD", "side": "BUY", "entry": 1.1, "stop_loss": 1.09,
                     "take_profit": 1.12, "risk_amount": 10.0,
                     "account_id": 123, "environment": "demo"},
            access_token="token",
        )
        self.assertEqual(result["status"], "confirmed_open")
        self.assertEqual(result["position_id"], 555)
        self.assertEqual(len(manager.orders), 1)
        order = manager.orders[0]
        self.assertEqual(order["volume"], 100000)
        self.assertEqual(order["kwargs"]["stop_loss"], 1.09)
        self.assertEqual(order["kwargs"]["take_profit"], 1.12)
        self.assertEqual(order["kwargs"]["client_order_id"], "TG0000000007E")

    async def test_unconfirmed_when_broker_reports_no_matching_position(self):
        from app.ctrader_worker import execute_verified_ctrader_entry

        manager = FakeManager(deposit_asset_id=2)
        result = await execute_verified_ctrader_entry(
            manager=manager, command_id=8, user_id="user-1", account_id=123,
            environment="demo",
            payload={"symbol": "EURUSD", "side": "BUY", "entry": 1.1, "stop_loss": 1.09,
                     "take_profit": 1.12, "risk_amount": 10.0,
                     "account_id": 123, "environment": "demo"},
            access_token="token",
        )
        self.assertEqual(result["status"], "submitted_unconfirmed")
        self.assertEqual(len(manager.orders), 1)

    async def test_unverified_symbol_never_reaches_the_order_call(self):
        from app.ctrader_worker import execute_verified_ctrader_entry

        manager = FakeManager(deposit_asset_id=2)
        with self.assertRaisesRegex(RuntimeError, "not audited currency assets"):
            await execute_verified_ctrader_entry(
                manager=manager, command_id=9, user_id="user-1", account_id=123,
                environment="demo",
                payload={"symbol": "XAUUSD", "side": "BUY", "entry": 2400.0, "stop_loss": 2390.0,
                         "take_profit": 2420.0, "risk_amount": 10.0,
                         "account_id": 123, "environment": "demo"},
                access_token="token",
            )
        self.assertEqual(manager.orders, [])

    async def test_invalid_payload_never_reaches_the_broker(self):
        from app.ctrader_worker import execute_verified_ctrader_entry

        manager = FakeManager(deposit_asset_id=2)
        for bad in (
            {"symbol": "EURUSD", "side": "BUY", "entry": 1.1, "stop_loss": 1.09, "take_profit": 1.12},
            {"symbol": "EURUSD", "side": "HOLD", "entry": 1.1, "stop_loss": 1.09, "take_profit": 1.12, "risk_amount": 10.0},
            {"symbol": "", "side": "BUY", "entry": 1.1, "stop_loss": 1.09, "take_profit": 1.12, "risk_amount": 10.0},
        ):
            with self.subTest(payload=bad), self.assertRaises(RuntimeError):
                await execute_verified_ctrader_entry(
                    manager=manager, command_id=10, user_id="user-1", account_id=123,
                    environment="demo", payload=bad, access_token="token",
                )
        self.assertEqual(manager.orders, [])

    async def test_live_environment_never_reaches_the_broker(self):
        from app.ctrader_worker import execute_verified_ctrader_entry

        manager = FakeManager(deposit_asset_id=2)
        with self.assertRaisesRegex(RuntimeError, "Live accounts"):
            await execute_verified_ctrader_entry(
                manager=manager, command_id=11, user_id="user-1", account_id=123,
                environment="live",
                payload={"symbol": "EURUSD", "side": "BUY", "entry": 1.1, "stop_loss": 1.09,
                         "take_profit": 1.12, "risk_amount": 10.0,
                         "account_id": 123, "environment": "live"},
                access_token="token",
            )
        self.assertEqual(manager.orders, [])


if __name__ == "__main__":
    unittest.main()
