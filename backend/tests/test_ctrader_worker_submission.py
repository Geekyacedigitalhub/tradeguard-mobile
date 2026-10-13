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
    def __init__(self, command_type, payload):
        self.command_type = command_type
        self.payload = payload

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
            return FakeResult([(True, False)])
        return FakeResult()


class CTraderSubmissionUncertaintyTests(unittest.IsolatedAsyncioTestCase):
    async def _run_command(self, command_type, payload, submit_method):
        fake_connection = WorkerConnection(command_type, payload)
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

    async def test_protection_submission_timeout_is_unconfirmed_not_failed(self):
        await self._run_command(
            "protect_position",
            {"execution_provider": "ctrader", "account_id": 123, "environment": "demo",
             "position_id": 77, "stop_loss": 1.0, "take_profit": 2.0},
            "protect_position",
        )

    async def test_automated_entry_never_reaches_broker_without_verified_sizing(self):
        fake_connection = WorkerConnection(
            "open_market",
            {"execution_provider": "ctrader", "account_id": 123, "environment": "demo",
             "risk_amount": 5, "symbol": "EURUSD", "side": "BUY", "volume": 100},
        )
        finished = []
        open_market = AsyncMock()
        with patch.object(ctrader_worker, "connection", return_value=fake_connection), \
             patch.object(ctrader_worker, "_fail_stale_ctrader_commands"), \
             patch.object(ctrader_worker, "fresh_access_token", return_value="test-token"), \
             patch.object(ctrader_worker.manager, "authorize_account", new=AsyncMock()), \
             patch.object(ctrader_worker.manager, "remember_account"), \
             patch.object(ctrader_worker, "_finish", side_effect=lambda command_id, result, status: finished.append((result, status))), \
             patch.object(ctrader_worker, "_publish_position_alert"), \
             patch.object(ctrader_worker.manager, "open_market", new=open_market, create=True):
            await ctrader_worker.process_ctrader_commands()

        self.assertEqual(len(finished), 1)
        self.assertEqual(finished[0][1], "failed")
        self.assertIn("risk sizing", finished[0][0]["error"].lower())
        open_market.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
