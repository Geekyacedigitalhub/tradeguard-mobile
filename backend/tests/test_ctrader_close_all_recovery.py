import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("JWT_SECRET", "unit-test-only-not-a-real-secret")

from app import ctrader_worker


class Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class Connection:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        q = " ".join(query.split())
        if "UPDATE bridge_commands bc" in q and "SET status='processing'" in q:
            return Result([(1, "user-1", "close_all_positions", {
                "execution_provider": "ctrader", "account_id": 123,
                "environment": "demo", "manual_close": True,
            })])
        if "SELECT account_id,environment FROM ctrader_connections" in q:
            return Result([(123, "demo")])
        if "SELECT running,emergency_stopped FROM bot_state" in q:
            return Result([(False, False)])
        return Result()


class CTraderCloseAllRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_submission_timeout_does_not_prevent_remaining_close_attempts(self):
        positions = [
            SimpleNamespace(positionId=77, tradeData=SimpleNamespace(volume=100)),
            SimpleNamespace(positionId=78, tradeData=SimpleNamespace(volume=200)),
        ]
        before = SimpleNamespace(position=positions)
        after = SimpleNamespace(position=[])

        with patch("app.ctrader_worker.connection", return_value=Connection()), \
             patch.object(ctrader_worker, "_fail_stale_ctrader_commands"), \
             patch.object(ctrader_worker, "fresh_access_token", return_value="test-token"), \
             patch.object(ctrader_worker.manager, "authorize_account", new=AsyncMock()), \
             patch.object(ctrader_worker.manager, "remember_account"), \
             patch.object(ctrader_worker.manager, "reconcile", new=AsyncMock(side_effect=[before, after])), \
             patch.object(ctrader_worker.manager, "close_position", new=AsyncMock(side_effect=[TimeoutError("network timeout"), "ok"])) as close, \
             patch.object(ctrader_worker, "_assert_selected_account_binding"), \
             patch.object(ctrader_worker, "position_volume_snapshot", return_value=None), \
             patch.object(ctrader_worker, "classify_close_result", return_value="confirmed_closed"), \
             patch.object(ctrader_worker, "_finish") as finish, \
             patch.object(ctrader_worker, "_publish_position_alert"):
            await ctrader_worker.process_ctrader_commands()

        self.assertEqual(close.await_count, 2)
        result = finish.call_args.args[1]
        self.assertEqual(finish.call_args.args[2], "completed")
        self.assertEqual(result["status"], "partially_closed")
        self.assertEqual(result["attempted_count"], 2)
        self.assertEqual(result["confirmed_closed_count"], 1)
        self.assertEqual(result["positions"][0]["status"], "unconfirmed")
        self.assertEqual(result["positions"][1]["status"], "confirmed_closed")

    async def test_duplicate_position_ids_block_the_entire_close_all_batch(self):
        duplicate_positions = [
            SimpleNamespace(positionId=77, tradeData=SimpleNamespace(volume=100)),
            SimpleNamespace(positionId=77, tradeData=SimpleNamespace(volume=200)),
        ]
        before = SimpleNamespace(position=duplicate_positions)

        with patch("app.ctrader_worker.connection", return_value=Connection()), \\
             patch.object(ctrader_worker, "_fail_stale_ctrader_commands"), \\
             patch.object(ctrader_worker, "fresh_access_token", return_value="test-token"), \\
             patch.object(ctrader_worker.manager, "authorize_account", new=AsyncMock()), \\
             patch.object(ctrader_worker.manager, "remember_account"), \\
             patch.object(ctrader_worker.manager, "reconcile", new=AsyncMock(return_value=before)), \\
             patch.object(ctrader_worker.manager, "close_position", new=AsyncMock()) as close, \\
             patch.object(ctrader_worker, "_assert_selected_account_binding"), \\
             patch.object(ctrader_worker, "_finish") as finish, \\
             patch.object(ctrader_worker, "_publish_position_alert"):
            await ctrader_worker.process_ctrader_commands()

        close.assert_not_awaited()
        result = finish.call_args.args[1]
        self.assertEqual(finish.call_args.args[2], "completed")
        self.assertEqual(result["status"], "unconfirmed")
        self.assertEqual(result["attempted_count"], 0)
        self.assertIn("duplicate position IDs", result["reason"])


if __name__ == "__main__":
    unittest.main()
