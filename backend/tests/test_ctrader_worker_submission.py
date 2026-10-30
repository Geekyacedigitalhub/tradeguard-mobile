import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("JWT_SECRET", "unit-test-only-not-a-real-secret")

from app import ctrader_worker


class FakeResult:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class WorkerConnection:
    def __init__(self, command_type, payload, bot_state=(True, False), command_status="processing"):
        self.command_type = command_type
        self.payload = payload
        self.bot_state = bot_state
        self.command_status = command_status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        normalized = " ".join(query.split())
        if "UPDATE bridge_commands bc" in normalized and "SET status='processing'" in normalized:
            return FakeResult([(1, "user-1", self.command_type, self.payload)])
        if "SELECT account_id,environment FROM ctrader_connections" in normalized:
            return FakeResult([(123, "demo")])
        if "SELECT running,emergency_stopped FROM bot_state" in normalized:
            return FakeResult([self.bot_state])
        if "SELECT status FROM bridge_commands" in normalized:
            return FakeResult([(self.command_status,)])
        return FakeResult()


class CTraderSubmissionUncertaintyTests(unittest.IsolatedAsyncioTestCase):
    async def _run_command(self, command_type, payload, submit_method, bot_state=(True, False)):
        fake_connection = WorkerConnection(command_type, payload, bot_state=bot_state)
        finished = []
        alerts = []

        async def authorize(*args, **kwargs):
            return None

        async def reconcile(*args, **kwargs):
            return object()

        with patch.object(ctrader_worker, "connection", return_value=fake_connection), \
             patch.object(ctrader_worker, "_fail_stale_ctrader_commands"), \
             patch.object(ctrader_worker, "fresh_access_token", return_value="test-token"), \
             patch.object(ctrader_worker.manager, "authorize_account", new=AsyncMock(side_effect=authorize)), \
             patch.object(ctrader_worker.manager, "remember_account"), \
             patch.object(ctrader_worker.manager, "reconcile", new=AsyncMock(side_effect=reconcile)), \
             patch.object(ctrader_worker, "_assert_selected_account_binding"), \
             patch.object(ctrader_worker, "_finish", side_effect=lambda command_id, result, status: finished.append((result, status))), \
             patch.object(ctrader_worker, "_publish_position_alert", side_effect=lambda *a, **kw: alerts.append((a, kw))), \
             patch.object(ctrader_worker.manager, submit_method, new=AsyncMock(side_effect=TimeoutError("broker transport timed out"))), \
             patch.object(ctrader_worker, "protection_snapshot", return_value={"stop_loss": 1.0, "take_profit": 2.0}), \
             patch.object(ctrader_worker, "position_volume_snapshot", return_value=100):
            await ctrader_worker.process_ctrader_commands()

        self.assertEqual(len(finished), 1)
        self.assertEqual(finished[0][1], "completed")
        self.assertEqual(finished[0][0]["status"], "submitted_unconfirmed")
        self.assertIn("submission_error", finished[0][0])
        self.assertEqual(len(alerts), 1)
        self.assertFalse(alerts[0][1].get("failed", False))

    async def test_close_submission_timeout_is_unconfirmed_not_failed(self):
        await self._run_command(
            "close_position",
            {"execution_provider": "ctrader", "account_id": 123, "environment": "demo",
             "manual_close": True, "position_id": 77, "volume": 100},
            "close_position",
        )

    async def test_stale_failed_close_command_cannot_submit_broker_action(self):
        fake_connection = WorkerConnection(
            "close_position",
            {"execution_provider": "ctrader", "account_id": 123, "environment": "demo",
             "manual_close": True, "position_id": 77, "volume": 100},
            command_status="failed",
        )
        finished = []
        close_position = AsyncMock()
        with patch.object(ctrader_worker, "connection", return_value=fake_connection), \
             patch.object(ctrader_worker, "_fail_stale_ctrader_commands"), \
             patch.object(ctrader_worker, "fresh_access_token", return_value="test-token"), \
             patch.object(ctrader_worker.manager, "authorize_account", new=AsyncMock()), \
             patch.object(ctrader_worker.manager, "remember_account"), \
             patch.object(ctrader_worker.manager, "reconcile", new=AsyncMock(return_value=object())), \
             patch.object(ctrader_worker, "_assert_selected_account_binding"), \
             patch.object(ctrader_worker, "_finish", side_effect=lambda command_id, result, status: finished.append((result, status))), \
             patch.object(ctrader_worker, "_publish_position_alert"), \
             patch.object(ctrader_worker.manager, "close_position", new=close_position), \
             patch.object(ctrader_worker, "position_volume_snapshot", return_value=100):
            await ctrader_worker.process_ctrader_commands()

        close_position.assert_not_awaited()
        self.assertEqual(len(finished), 1)
        self.assertEqual(finished[0][1], "failed")
        self.assertIn("no longer owns an active execution claim", finished[0][0]["error"])

    async def test_stale_failed_close_all_command_cannot_submit_broker_action(self):
        fake_connection = WorkerConnection(
            "close_all_positions",
            {"execution_provider": "ctrader", "account_id": 123, "environment": "demo",
             "manual_close": True},
            command_status="failed",
        )
        positions = [type("Position", (), {
            "positionId": 77, "tradeData": type("TradeData", (), {"volume": 100})()
        })()]
        finished = []
        close_position = AsyncMock()
        with patch.object(ctrader_worker, "connection", return_value=fake_connection), \
             patch.object(ctrader_worker, "_fail_stale_ctrader_commands"), \
             patch.object(ctrader_worker, "fresh_access_token", return_value="test-token"), \
             patch.object(ctrader_worker.manager, "authorize_account", new=AsyncMock()), \
             patch.object(ctrader_worker.manager, "remember_account"), \
             patch.object(ctrader_worker.manager, "reconcile", new=AsyncMock(return_value=type("Snapshot", (), {"position": positions})())), \
             patch.object(ctrader_worker, "_assert_selected_account_binding"), \
             patch.object(ctrader_worker, "_finish", side_effect=lambda command_id, result, status: finished.append((result, status))), \
             patch.object(ctrader_worker, "_publish_position_alert"), \
             patch.object(ctrader_worker.manager, "close_position", new=close_position):
            await ctrader_worker.process_ctrader_commands()

        close_position.assert_not_awaited()
        self.assertEqual(len(finished), 1)
        self.assertEqual(finished[0][1], "completed")
        self.assertEqual(finished[0][0]["status"], "unconfirmed")
        self.assertIn("no longer owns an active execution claim", finished[0][0]["positions"][0]["reason"])

    async def test_stale_failed_protection_command_cannot_submit_broker_action(self):
        fake_connection = WorkerConnection(
            "protect_position",
            {"execution_provider": "ctrader", "account_id": 123, "environment": "demo",
             "position_id": 77, "stop_loss": 1.0, "take_profit": 2.0},
            command_status="failed",
        )
        finished = []
        protect_position = AsyncMock()
        with patch.object(ctrader_worker, "connection", return_value=fake_connection), \
             patch.object(ctrader_worker, "_fail_stale_ctrader_commands"), \
             patch.object(ctrader_worker, "fresh_access_token", return_value="test-token"), \
             patch.object(ctrader_worker.manager, "authorize_account", new=AsyncMock()), \
             patch.object(ctrader_worker.manager, "remember_account"), \
             patch.object(ctrader_worker.manager, "reconcile", new=AsyncMock(return_value=object())), \
             patch.object(ctrader_worker, "_assert_selected_account_binding"), \
             patch.object(ctrader_worker, "_finish", side_effect=lambda command_id, result, status: finished.append((result, status))), \
             patch.object(ctrader_worker, "_publish_position_alert"), \
             patch.object(ctrader_worker.manager, "protect_position", new=protect_position), \
             patch.object(ctrader_worker, "protection_snapshot", return_value={"stop_loss": 1.0, "take_profit": 2.0}):
            await ctrader_worker.process_ctrader_commands()

        protect_position.assert_not_awaited()
        self.assertEqual(len(finished), 1)
        self.assertEqual(finished[0][1], "failed")
        self.assertIn("no longer owns an active execution claim", finished[0][0]["error"])

    async def test_protection_submission_timeout_is_unconfirmed_not_failed(self):
        await self._run_command(
            "protect_position",
            {"execution_provider": "ctrader", "account_id": 123, "environment": "demo",
             "position_id": 77, "stop_loss": 1.0, "take_profit": 2.0},
            "protect_position",
        )

    async def test_incomplete_entry_payload_never_reaches_broker_before_authorization(self):
        # The payload lacks entry/stop_loss/take_profit, so it must be
        # rejected before any broker session is requested or refreshed.
        fake_connection = WorkerConnection(
            "open_market",
            {"execution_provider": "ctrader", "account_id": 123, "environment": "demo",
             "risk_amount": 5, "symbol": "EURUSD", "side": "BUY", "volume": 100},
        )
        finished = []
        new_market_order = AsyncMock()
        fresh_token = unittest.mock.Mock(return_value="test-token")
        authorize = AsyncMock()
        with patch.object(ctrader_worker, "connection", return_value=fake_connection), \
             patch.object(ctrader_worker, "_fail_stale_ctrader_commands"), \
             patch.object(ctrader_worker, "fresh_access_token", new=fresh_token), \
             patch.object(ctrader_worker.manager, "authorize_account", new=authorize), \
             patch.object(ctrader_worker.manager, "remember_account"), \
             patch.object(ctrader_worker, "_finish", side_effect=lambda command_id, result, status: finished.append((result, status))), \
             patch.object(ctrader_worker, "_publish_position_alert"), \
             patch.object(ctrader_worker.manager, "new_market_order", new=new_market_order), \
             patch.object(ctrader_worker, "notification_event"), \
             patch.object(ctrader_worker, "send_push"):
            await ctrader_worker.process_ctrader_commands()

        self.assertEqual(len(finished), 1)
        self.assertEqual(finished[0][1], "failed")
        self.assertIn("entry", finished[0][0]["error"].lower())
        fresh_token.assert_not_called()
        authorize.assert_not_awaited()
        new_market_order.assert_not_awaited()


    async def test_stopped_bot_rejects_entry_before_broker_authorization(self):
        fake_connection = WorkerConnection(
            "open_market",
            {"execution_provider": "ctrader", "account_id": 123, "environment": "demo",
             "risk_amount": 5, "symbol": "EURUSD", "side": "BUY", "volume": 100},
            bot_state=(False, False),
        )
        finished = []
        authorize = AsyncMock()
        open_market = AsyncMock()
        with patch.object(ctrader_worker, "connection", return_value=fake_connection), \
             patch.object(ctrader_worker, "_fail_stale_ctrader_commands"), \
             patch.object(ctrader_worker, "fresh_access_token", return_value="test-token"), \
             patch.object(ctrader_worker.manager, "authorize_account", new=authorize), \
             patch.object(ctrader_worker.manager, "remember_account"), \
             patch.object(ctrader_worker, "_finish", side_effect=lambda command_id, result, status: finished.append((result, status))), \
             patch.object(ctrader_worker, "_publish_position_alert"), \
             patch.object(ctrader_worker.manager, "open_market", new=open_market, create=True):
            await ctrader_worker.process_ctrader_commands()

        self.assertEqual(len(finished), 1)
        self.assertEqual(finished[0][1], "failed")
        self.assertIn("not running", finished[0][0]["error"].lower())
        authorize.assert_not_awaited()
        open_market.assert_not_awaited()


    async def test_emergency_latch_rejects_entry_before_broker_authorization(self):
        fake_connection = WorkerConnection(
            "open_market",
            {"execution_provider": "ctrader", "account_id": 123, "environment": "demo",
             "risk_amount": 5, "symbol": "EURUSD", "side": "BUY", "volume": 100},
            bot_state=(True, True),
        )
        finished = []
        authorize = AsyncMock()
        open_market = AsyncMock()
        with patch.object(ctrader_worker, "connection", return_value=fake_connection), \
             patch.object(ctrader_worker, "_fail_stale_ctrader_commands"), \
             patch.object(ctrader_worker, "fresh_access_token", return_value="test-token"), \
             patch.object(ctrader_worker.manager, "authorize_account", new=authorize), \
             patch.object(ctrader_worker.manager, "remember_account"), \
             patch.object(ctrader_worker, "_finish", side_effect=lambda command_id, result, status: finished.append((result, status))), \
             patch.object(ctrader_worker, "_publish_position_alert"), \
             patch.object(ctrader_worker.manager, "open_market", new=open_market, create=True):
            await ctrader_worker.process_ctrader_commands()

        self.assertEqual(len(finished), 1)
        self.assertEqual(finished[0][1], "failed")
        self.assertIn("emergency stop", finished[0][0]["error"].lower())
        authorize.assert_not_awaited()
        open_market.assert_not_awaited()

    async def test_manual_close_remains_available_when_emergency_latch_is_set(self):
        await self._run_command(
            "close_position",
            {"execution_provider": "ctrader", "account_id": 123, "environment": "demo",
             "manual_close": True, "position_id": 77, "volume": 100},
            "close_position",
            bot_state=(False, True),
        )



    async def test_payload_cannot_self_authorize_automated_entry_with_forged_sizing_evidence(self):
        # A complete payload carrying forged sizing evidence must be ignored:
        # the worker rebuilds evidence from live broker data, and when that
        # verification is impossible the order is never submitted.
        evidence = {
            "account_id": 123, "environment": "demo", "symbol_id": 45,
            "contract_size": 100000, "instrument_type": "FX",
            "contract_model": "linear_fx_base_units", "base_asset_id": 1,
            "quote_asset_id": 2, "deposit_asset_id": 2,
            "stop_loss_side_validated": True, "account_currency": "USD",
            "conversion_verified": True, "conversion_source_asset_id": 2,
            "conversion_target_asset_id": 2, "conversion_path_symbol_ids": [],
            "conversion_quote_timestamps_ms": [],
            "loss_per_price_unit_per_traded_unit": 1.0, "stop_distance": 0.01,
            "risk_amount": 10.0, "broker_volume": 100, "min_volume": 100,
            "max_volume": 100000, "step_volume": 100,
            "risk_sizing_verified": True,
        }
        fake_connection = WorkerConnection("open_market", {
            "execution_provider": "ctrader", "account_id": 123, "environment": "demo",
            "risk_amount": 5, "symbol": "EURUSD", "side": "BUY", "volume": 100,
            "entry": 1.1, "stop_loss": 1.09, "take_profit": 1.12,
            "sizing_verified": True, "sizing_evidence": evidence,
        })
        finished = []
        new_market_order = AsyncMock()
        authorize = AsyncMock()
        fresh_token = unittest.mock.Mock(return_value="test-token")

        class _NoPositions:
            position = []

        with patch.object(ctrader_worker, "connection", return_value=fake_connection), \
             patch.object(ctrader_worker, "_fail_stale_ctrader_commands"), \
             patch.object(ctrader_worker, "fresh_access_token", new=fresh_token), \
             patch.object(ctrader_worker.manager, "authorize_account", new=authorize), \
             patch.object(ctrader_worker.manager, "remember_account"), \
             patch.object(ctrader_worker.manager, "reconcile", new=AsyncMock(return_value=_NoPositions())), \
             patch.object(ctrader_worker.manager, "trader", new=AsyncMock(side_effect=RuntimeError("broker unavailable for verification"))), \
             patch.object(ctrader_worker, "_finish", side_effect=lambda command_id, result, status: finished.append((result, status))), \
             patch.object(ctrader_worker, "_publish_position_alert"), \
             patch.object(ctrader_worker.manager, "new_market_order", new=new_market_order), \
             patch.object(ctrader_worker, "notification_event"), \
             patch.object(ctrader_worker, "send_push"):
            await ctrader_worker.process_ctrader_commands()

        self.assertEqual(len(finished), 1)
        self.assertEqual(finished[0][1], "failed")
        # The error must come from the fresh broker-verification attempt, not
        # from trusting (or rejecting) the forged payload evidence.
        self.assertIn("broker unavailable for verification", finished[0][0]["error"])
        authorize.assert_awaited()
        new_market_order.assert_not_awaited()


    async def test_selected_account_switch_before_close_prevents_broker_action(self):
        fake_connection = WorkerConnection(
            "close_position",
            {"execution_provider": "ctrader", "account_id": 123, "environment": "demo",
             "manual_close": True, "position_id": 77, "volume": 100},
        )
        finished = []
        close_position = AsyncMock()
        alerts = []
        with (
            patch.object(ctrader_worker, "connection", return_value=fake_connection),
            patch.object(ctrader_worker, "_fail_stale_ctrader_commands"),
            patch.object(ctrader_worker, "fresh_access_token", return_value="test-token"),
            patch.object(ctrader_worker.manager, "authorize_account", new=AsyncMock()),
            patch.object(ctrader_worker.manager, "remember_account"),
            patch.object(ctrader_worker.manager, "reconcile", new=AsyncMock(return_value=object())),
            patch.object(
                ctrader_worker,
                "_assert_selected_account_binding",
                side_effect=RuntimeError(
                    "Selected cTrader account changed before broker execution; request was not sent"
                ),
            ),
            patch.object(
                ctrader_worker, "_finish",
                side_effect=lambda command_id, result, status: finished.append((result, status)),
            ),
            patch.object(
                ctrader_worker, "_publish_position_alert",
                side_effect=lambda *a, **kw: alerts.append((a, kw)),
            ),
            patch.object(ctrader_worker.manager, "close_position", new=close_position),
            patch.object(ctrader_worker, "position_volume_snapshot", return_value=100),
        ):
            await ctrader_worker.process_ctrader_commands()

        close_position.assert_not_awaited()
        self.assertEqual(len(finished), 1)
        self.assertEqual(finished[0][1], "failed")
        self.assertIn("account changed", finished[0][0]["error"].lower())
        self.assertEqual(len(alerts), 1)
        self.assertTrue(alerts[0][1].get("failed", False))


    async def test_close_all_halts_remaining_positions_after_account_switch(self):
        fake_connection = WorkerConnection(
            "close_all_positions",
            {"execution_provider": "ctrader", "account_id": 123, "environment": "demo",
             "manual_close": True},
        )
        positions = [
            type("Position", (), {
                "positionId": position_id,
                "tradeData": type("TradeData", (), {"volume": 100})(),
            })()
            for position_id in (77, 78, 79)
        ]
        snapshot = type("Snapshot", (), {"position": positions})()
        finished = []
        alerts = []
        close_position = AsyncMock(return_value={"ok": True})
        binding = unittest.mock.Mock(side_effect=[
            None,
            RuntimeError("Selected cTrader account changed before broker execution; request was not sent"),
        ])
        with (
            patch.object(ctrader_worker, "connection", return_value=fake_connection),
            patch.object(ctrader_worker, "_fail_stale_ctrader_commands"),
            patch.object(ctrader_worker, "fresh_access_token", return_value="test-token"),
            patch.object(ctrader_worker.manager, "authorize_account", new=AsyncMock()),
            patch.object(ctrader_worker.manager, "remember_account"),
            patch.object(ctrader_worker.manager, "reconcile", new=AsyncMock(return_value=snapshot)),
            patch.object(ctrader_worker, "_assert_selected_account_binding", new=binding),
            patch.object(ctrader_worker, "_finish", side_effect=lambda command_id, result, status: finished.append((result, status))),
            patch.object(ctrader_worker, "_publish_position_alert", side_effect=lambda *a, **kw: alerts.append((a, kw))),
            patch.object(ctrader_worker.manager, "close_position", new=close_position),
            patch.object(ctrader_worker, "position_volume_snapshot", return_value=None),
        ):
            await ctrader_worker.process_ctrader_commands()

        self.assertEqual(close_position.await_count, 1)
        self.assertEqual([call.args[1] for call in close_position.await_args_list], [77])
        self.assertEqual(len(finished), 1)
        self.assertEqual(finished[0][1], "completed")
        result = finished[0][0]
        self.assertEqual(result["status"], "partially_closed")
        self.assertEqual(result["attempted_count"], 3)
        self.assertEqual(result["confirmed_closed_count"], 1)
        self.assertEqual([item["status"] for item in result["positions"]],
                         ["confirmed_closed", "unconfirmed", "unconfirmed"])
        self.assertEqual(len(alerts), 1)


if __name__ == "__main__":
    unittest.main()
