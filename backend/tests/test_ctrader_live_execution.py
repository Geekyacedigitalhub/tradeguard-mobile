import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import os

os.environ.setdefault("JWT_SECRET", "unit-test-only-not-a-real-secret")

from app.ctrader_verified_entry import (
    LIVE_MAX_DAILY_LOSS_PCT,
    LIVE_MAX_DRAWDOWN_PCT,
    LIVE_MAX_RISK_MULTIPLIER,
    LIVE_MAX_RISK_PCT,
    build_verified_sizing_evidence,
)
from app.ctrader_execution_guard import entry_block_reason, command_block_reason
from app.risk_api import scale_risk_envelope_for_multiplier
from test_ctrader_verified_entry import FakeManager


class LiveEnvelopeScalingTests(unittest.TestCase):
    def test_x100_profile_is_capped_on_live(self):
        risk, daily, dd = scale_risk_envelope_for_multiplier(
            0.5, 2.0, 5.0, 100.0,
            live_caps=(LIVE_MAX_RISK_PCT, LIVE_MAX_DAILY_LOSS_PCT, LIVE_MAX_DRAWDOWN_PCT),
        )
        self.assertEqual(risk, LIVE_MAX_RISK_PCT)
        self.assertEqual(daily, LIVE_MAX_DAILY_LOSS_PCT)
        self.assertEqual(dd, LIVE_MAX_DRAWDOWN_PCT)

    def test_aggressive_multiplier_stays_under_the_cap(self):
        risk, daily, dd = scale_risk_envelope_for_multiplier(
            0.5, 2.0, 5.0, 40.0,
            live_caps=(LIVE_MAX_RISK_PCT, LIVE_MAX_DAILY_LOSS_PCT, LIVE_MAX_DRAWDOWN_PCT),
        )
        self.assertLessEqual(risk, LIVE_MAX_RISK_PCT)
        self.assertLessEqual(daily, LIVE_MAX_DAILY_LOSS_PCT)
        self.assertLessEqual(dd, LIVE_MAX_DRAWDOWN_PCT)

    def test_moderate_multiplier_hits_the_caps(self):
        # 0.5% x 4 = 2% per trade (right at the cap); daily 2% x 4 = 8%
        # is pulled back to the 6% hard stop; drawdown 20% -> 12%.
        risk, daily, dd = scale_risk_envelope_for_multiplier(
            0.5, 2.0, 5.0, 4.0,
            live_caps=(LIVE_MAX_RISK_PCT, LIVE_MAX_DAILY_LOSS_PCT, LIVE_MAX_DRAWDOWN_PCT),
        )
        self.assertEqual(risk, 2.0)
        self.assertEqual(daily, 6.0)
        self.assertEqual(dd, 12.0)

    def test_conservative_multiplier_is_not_capped(self):
        risk, daily, dd = scale_risk_envelope_for_multiplier(
            0.5, 2.0, 5.0, 2.0,
            live_caps=(LIVE_MAX_RISK_PCT, LIVE_MAX_DAILY_LOSS_PCT, LIVE_MAX_DRAWDOWN_PCT),
        )
        self.assertEqual(risk, 1.0)
        self.assertEqual(daily, 4.0)
        self.assertEqual(dd, 10.0)

    def test_live_caps_are_validated(self):
        for bad in ((), (2.0,), (2.0, 6.0, 12.0, 1.0), (0, 6.0, 12.0), (2.0, -6.0, 12.0),
                    (2.0, 6.0, 101.0), (True, 6.0, 12.0), ("2", 6.0, 12.0), None and ()):
            if bad is None:
                continue
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                scale_risk_envelope_for_multiplier(0.5, 2.0, 5.0, 10.0, live_caps=bad)

    def test_demo_scaling_is_unchanged_without_live_caps(self):
        risk, daily, dd = scale_risk_envelope_for_multiplier(0.5, 2.0, 5.0, 100.0)
        self.assertEqual((risk, daily, dd), (50.0, 100.0, 100.0))


def _valid_live_evidence(**overrides):
    """A complete, consistent Live evidence document (same-currency EURUSD/USD)."""
    evidence = {
        "account_id": 123,
        "environment": "live",
        "symbol_id": 42,
        "contract_size": 100000,
        "instrument_type": "FX",
        "contract_model": "linear_fx_base_units",
        "base_asset_id": 1,
        "quote_asset_id": 2,
        "deposit_asset_id": 2,
        "stop_loss_side_validated": True,
        "account_currency": "USD",
        "conversion_verified": True,
        "conversion_source_asset_id": 2,
        "conversion_target_asset_id": 2,
        "conversion_path_symbol_ids": [],
        "conversion_quote_timestamps_ms": [],
        "loss_per_price_unit_per_traded_unit": 1.0,
        "stop_distance": 0.01,
        "risk_amount": 10.0,
        "broker_volume": 100000,
        "min_volume": 100,
        "max_volume": 1000000,
        "step_volume": 100,
        "account_balance": 10000.0,
        "live_risk_cap_amount": 200.0,
        "risk_sizing_verified": True,
    }
    evidence.update(overrides)
    return evidence


class LiveGuardContractTests(unittest.TestCase):
    def test_valid_live_evidence_passes(self):
        self.assertIsNone(entry_block_reason(
            "live", sizing_verified=True, sizing_evidence=_valid_live_evidence(),
            expected_account_id=123, expected_symbol_id=42,
        ))

    def test_risk_above_the_hard_cap_is_blocked(self):
        reason = entry_block_reason(
            "live", sizing_verified=True,
            sizing_evidence=_valid_live_evidence(risk_amount=201.0),
            expected_account_id=123, expected_symbol_id=42,
        )
        self.assertIn("hard per-trade cap", reason)

    def test_risk_exactly_at_the_cap_passes(self):
        self.assertIsNone(entry_block_reason(
            "live", sizing_verified=True,
            sizing_evidence=_valid_live_evidence(risk_amount=200.0, broker_volume=20000000)
            if 20000000 <= 1000000 else _valid_live_evidence(
                risk_amount=200.0, broker_volume=200000,
                stop_distance=0.1,
            ),
            expected_account_id=123, expected_symbol_id=42,
        ))

    def test_missing_live_fields_are_blocked(self):
        for field in ("account_balance", "live_risk_cap_amount"):
            evidence = _valid_live_evidence()
            evidence.pop(field)
            with self.subTest(field=field):
                reason = entry_block_reason(
                    "live", sizing_verified=True, sizing_evidence=evidence,
                    expected_account_id=123, expected_symbol_id=42,
                )
                self.assertIn(field, reason)

    def test_cap_larger_than_balance_is_blocked(self):
        reason = entry_block_reason(
            "live", sizing_verified=True,
            sizing_evidence=_valid_live_evidence(account_balance=100.0, live_risk_cap_amount=200.0),
            expected_account_id=123, expected_symbol_id=42,
        )
        self.assertIn("exceeds broker account balance", reason)

    def test_demo_evidence_must_not_carry_live_fields(self):
        reason = entry_block_reason(
            "demo", sizing_verified=True,
            sizing_evidence=_valid_live_evidence(environment="demo"),
            expected_account_id=123, expected_symbol_id=42,
        )
        self.assertIn("live-only risk fields", reason)

    def test_unknown_environment_is_blocked(self):
        # "LIVE" is intentionally NOT in the list: it normalizes to a valid
        # live environment (case-insensitive by design).
        for env in ("", "sandbox", "test", "prod"):
            reason = entry_block_reason(
                env, sizing_verified=True, sizing_evidence=_valid_live_evidence(),
                expected_account_id=123, expected_symbol_id=42,
            )
            with self.subTest(env=env):
                self.assertIsNotNone(reason)

    def test_command_policy_live(self):
        # Live entries are permitted; each one still passes the sizing guard.
        self.assertIsNone(command_block_reason("live", "open_market", {"manual_close": False}))
        # Live SL/TP amendments stay manual-only (done inside cTrader).
        self.assertIn("does not permit automated stop amendments",
                      command_block_reason("live", "protect_position", {}))
        # Closes still require explicit manual authorization on live.
        self.assertIsNone(command_block_reason("live", "close_position", {"manual_close": True}))
        self.assertIsNotNone(command_block_reason("live", "close_position", {"manual_close": False}))
        # Demo is unchanged.
        self.assertIsNone(command_block_reason("demo", "open_market", {}))
        self.assertIsNone(command_block_reason("demo", "protect_position", {}))


class LiveSizingEvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_evidence_carries_balance_and_cap(self):
        manager = FakeManager(deposit_asset_id=2)
        manager.trader_obj = SimpleNamespace(depositAssetId=2, traderLogin=49093168, balance=10000)
        evidence = await build_verified_sizing_evidence(
            manager=manager, user_id="user-1", account_id=123, environment="live",
            symbol_name="EURUSD", trade_side="BUY",
            entry_price=1.10, stop_price=1.09, target_price=1.12,
            risk_budget_account_currency=100.0, access_token="token",
        )
        self.assertEqual(evidence["environment"], "live")
        self.assertEqual(evidence["account_balance"], 10000.0)
        self.assertAlmostEqual(evidence["live_risk_cap_amount"], 200.0)
        self.assertLessEqual(evidence["risk_amount"], evidence["live_risk_cap_amount"])
        # The same evidence passes the guard with the live contract.
        self.assertIsNone(entry_block_reason(
            "live", sizing_verified=True, sizing_evidence=evidence,
            expected_account_id=123, expected_symbol_id=evidence["symbol_id"],
        ))

    async def test_live_budget_above_the_hard_cap_is_rejected_before_sizing(self):
        manager = FakeManager(deposit_asset_id=2)
        manager.trader_obj = SimpleNamespace(depositAssetId=2, traderLogin=49093168, balance=10000)
        with self.assertRaisesRegex(RuntimeError, "hard per-trade cap"):
            await build_verified_sizing_evidence(
                manager=manager, user_id="user-1", account_id=123, environment="live",
                symbol_name="EURUSD", trade_side="BUY",
                entry_price=1.10, stop_price=1.09, target_price=1.12,
                risk_budget_account_currency=300.0, access_token="token",
            )

    async def test_live_requires_a_positive_broker_balance(self):
        for balance in (None, 0, -5, float("inf"), "10000"):
            manager = FakeManager(deposit_asset_id=2)
            manager.trader_obj = SimpleNamespace(depositAssetId=2, balance=balance)
            with self.subTest(balance=balance), self.assertRaisesRegex(RuntimeError, "balance"):
                await build_verified_sizing_evidence(
                    manager=manager, user_id="user-1", account_id=123, environment="live",
                    symbol_name="EURUSD", trade_side="BUY",
                    entry_price=1.10, stop_price=1.09, target_price=1.12,
                    risk_budget_account_currency=10.0, access_token="token",
                )

    async def test_demo_evidence_has_no_live_fields(self):
        manager = FakeManager(deposit_asset_id=2)
        evidence = await build_verified_sizing_evidence(
            manager=manager, user_id="user-1", account_id=123, environment="demo",
            symbol_name="EURUSD", trade_side="BUY",
            entry_price=1.10, stop_price=1.09, target_price=1.12,
            risk_budget_account_currency=10.0, access_token="token",
        )
        self.assertEqual(evidence["environment"], "demo")
        self.assertNotIn("account_balance", evidence)
        self.assertNotIn("live_risk_cap_amount", evidence)


class LiveWorkerFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_entry_confirms_and_reports_live_environment(self):
        from app.ctrader_worker import execute_verified_ctrader_entry
        from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATradeSide

        manager = FakeManager(deposit_asset_id=2)
        manager.trader_obj = SimpleNamespace(depositAssetId=2, traderLogin=49093168, balance=100000)
        # Budget 100 / (0.01 * 100 pips) = 1,000,000 contract units.
        confirmed = SimpleNamespace(
            positionId=777,
            tradeData=SimpleNamespace(symbolId=42, volume=1000000, tradeSide=int(ProtoOATradeSide.BUY)),
        )

        async def reconcile_after(account_id, environment="live"):
            manager._call_count = getattr(manager, "_call_count", 0) + 1
            if manager._call_count >= 2:
                manager.reconcile_positions = [confirmed]
            return SimpleNamespace(position=manager.reconcile_positions)

        manager.reconcile = reconcile_after
        result = await execute_verified_ctrader_entry(
            manager=manager, command_id=21, user_id="user-1", account_id=123,
            environment="live",
            payload={"symbol": "EURUSD", "side": "BUY", "entry": 1.1, "stop_loss": 1.09,
                     "take_profit": 1.12, "risk_amount": 100.0,
                     "account_id": 123, "environment": "live"},
            access_token="token",
        )
        self.assertEqual(result["status"], "confirmed_open")
        self.assertEqual(result["environment"], "live")
        self.assertEqual(result["position_id"], 777)
        order = manager.orders[0]
        self.assertEqual(order["volume"], 1000000)
        self.assertEqual(order["kwargs"]["stop_loss"], 1.09)
        self.assertEqual(order["kwargs"]["take_profit"], 1.12)
        self.assertEqual(order["kwargs"]["client_order_id"], "TG0000000021E")

    async def test_live_budget_exceeding_cap_never_reaches_broker(self):
        from app.ctrader_worker import execute_verified_ctrader_entry

        manager = FakeManager(deposit_asset_id=2)
        manager.trader_obj = SimpleNamespace(depositAssetId=2, traderLogin=49093168, balance=10000)
        with self.assertRaisesRegex(RuntimeError, "hard per-trade cap"):
            await execute_verified_ctrader_entry(
                manager=manager, command_id=22, user_id="user-1", account_id=123,
                environment="live",
                payload={"symbol": "EURUSD", "side": "BUY", "entry": 1.1, "stop_loss": 1.09,
                         "take_profit": 1.12, "risk_amount": 500.0,
                         "account_id": 123, "environment": "live"},
                access_token="token",
            )
        self.assertEqual(manager.orders, [])

    async def test_worker_preflight_allows_live_entries(self):
        from app import ctrader_worker

        reason = ctrader_worker._preflight_command_block_reason(
            "live", 123, "open_market",
            {"execution_provider": "ctrader", "account_id": 123, "environment": "live"},
        )
        self.assertIsNone(reason)
        # Live SL/TP amendments are still blocked at the worker preflight.
        reason = ctrader_worker._preflight_command_block_reason(
            "live", 123, "protect_position",
            {"execution_provider": "ctrader", "account_id": 123, "environment": "live", "position_id": 5},
        )
        self.assertIsNotNone(reason)


class _Result:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class LiveFullAutoModeTests(unittest.IsolatedAsyncioTestCase):
    class _FakeConnection:
        def __init__(self, account_row, bot_row=(True, False, "semi_auto", 0.5, 2.0, 5, 5.0, "2026-11-01 00:00:00")):
            self.account_row = account_row
            self.bot_row = bot_row
            self.updates = []

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, query, params=None):
            normalized = " ".join(query.split())
            if normalized.startswith("SELECT running,emergency_stopped,mode,risk_per_trade"):
                return _Result(self.bot_row)
            if "FROM ctrader_connections" in normalized:
                return _Result(self.account_row)
            if normalized.startswith("UPDATE bot_state"):
                self.updates.append((normalized, params))
                # Reflect the mode change in the row get_bot() re-reads.
                self.bot_row = (self.bot_row[0], self.bot_row[1], params[0], *self.bot_row[3:])
                return _Result(None)
            return _Result(None)

    def _run_update_mode(self, mode, account_row):
        from app.main import HTTPException, ModeSettings, update_mode

        fake = self._FakeConnection(account_row)
        from app import main
        main._bot_state_cache.clear()
        with patch("app.main.connection", return_value=fake):
            try:
                result = update_mode(ModeSettings(mode=mode), {"id": "user-1"})
            except HTTPException as exc:
                result = exc
        return fake, result

    def test_full_auto_is_allowed_with_a_selected_live_account(self):
        fake, result = self._run_update_mode("full_auto", (24680, "live"))
        self.assertNotIsInstance(result, Exception)
        self.assertEqual(result["mode"], "full_auto")
        self.assertTrue(result["account_selected"])
        self.assertFalse(result["demo_account_selected"])
        self.assertEqual(result["execution_scope"], "live_fx_capped")
        self.assertTrue(result["automated_execution_allowed"])

    def test_full_auto_is_rejected_without_any_account(self):
        fake, result = self._run_update_mode("full_auto", None)
        self.assertIsInstance(result, Exception)
        self.assertIn("requires a selected cTrader account", str(result.detail))
        self.assertEqual(fake.updates, [])

    def test_full_auto_is_rejected_for_an_invalid_environment(self):
        fake, result = self._run_update_mode("full_auto", (123, "sandbox"))
        self.assertIsInstance(result, Exception)
        self.assertEqual(fake.updates, [])

    def test_get_bot_live_execution_reason(self):
        from app import main

        fake = self._FakeConnection((24680, "live"), bot_row=(True, False, "full_auto", 0.5, 2.0, 5, 5.0, "t"))
        main._bot_state_cache.clear()
        with patch("app.main.connection", return_value=fake):
            bot = main.get_bot({"id": "user-1"})
        self.assertTrue(bot["automated_execution_allowed"])
        self.assertEqual(bot["execution_scope"], "live_fx_capped")
        self.assertIn("2% per trade", bot["execution_reason"])
        main._bot_state_cache.clear()


if __name__ == "__main__":
    unittest.main()
