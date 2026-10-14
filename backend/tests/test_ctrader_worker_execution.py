"""Mocked end-to-end safety tests for the cTrader command worker."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app import ctrader_worker


def _db_contexts(command_row):
    queue_connection = MagicMock()
    queue_connection.__enter__.return_value = queue_connection
    queue_connection.execute.return_value.fetchall.return_value = [command_row]

    account_connection = MagicMock()
    account_connection.__enter__.return_value = account_connection
    account_connection.execute.return_value.fetchone.return_value = (123, "demo")
    return [queue_connection, account_connection]


class CTraderWorkerExecutionSafetyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.command = (
            77,
            "user-1",
            "open_market",
            {
                "execution_provider": "ctrader",
                "account_id": 123,
                "environment": "demo",
                "broker_volume": 250,
                "symbol": "EURUSD",
                "side": "BUY",
                "risk_amount": 10,
                "entry": 1.2,
                "stop_loss": 1.1,
                "take_profit": 1.4,
            },
        )
        self.light_symbol = SimpleNamespace(symbolId=7, symbolName="EURUSD")
        self.manager_patches = [
            patch.object(ctrader_worker.manager, "authorize_account", new_callable=AsyncMock),
            patch.object(ctrader_worker.manager, "remember_account"),
            patch.object(ctrader_worker.manager, "symbols", new_callable=AsyncMock),
            patch.object(ctrader_worker.manager, "symbol_by_id", new_callable=AsyncMock),
            patch.object(ctrader_worker.manager, "new_market_order", new_callable=AsyncMock),
            patch.object(ctrader_worker.manager, "protect_position", new_callable=AsyncMock),
        ]
        self.mocks = [p.start() for p in self.manager_patches]
        self.addCleanup(patch.stopall)
        (
            self.authorize,
            self.remember,
            self.symbols,
            self.symbol_by_id,
            self.new_order,
            self.protect,
        ) = self.mocks
        self.symbols.return_value = SimpleNamespace(symbol=[self.light_symbol])
        self.symbol_by_id.return_value = SimpleNamespace(
            minVolume=150, maxVolume=1000, stepVolume=100
        )
        self.new_order.return_value = SimpleNamespace(
            position=SimpleNamespace(positionId=9001)
        )

    async def _run_worker(self):
        contexts = _db_contexts(self.command)
        with (
            patch("app.ctrader_worker.connection", side_effect=contexts),
            patch("app.ctrader_worker.fresh_access_token", return_value="mock-token"),
            patch("app.ctrader_worker._finish") as finish,
        ):
            await ctrader_worker.process_ctrader_commands()
        return finish

    async def test_worker_fetches_full_symbol_and_sends_only_valid_volume(self):
        finish = await self._run_worker()

        self.symbol_by_id.assert_awaited_once_with(123, 7, "demo")
        self.new_order.assert_awaited_once_with(123, 7, "BUY", 250, "demo")
        self.protect.assert_awaited_once()
        finish.assert_called_once()
        self.assertEqual(finish.call_args.args[2], "completed")

    async def test_worker_rejects_invalid_full_symbol_limits_before_order(self):
        self.symbol_by_id.return_value = SimpleNamespace(
            minVolume=150, maxVolume=1000, stepVolume=0
        )

        finish = await self._run_worker()

        self.symbol_by_id.assert_awaited_once()
        self.new_order.assert_not_awaited()
        self.protect.assert_not_awaited()
        finish.assert_called_once()
        self.assertEqual(finish.call_args.args[2], "failed")
        self.assertIn("full-symbol volume limits", finish.call_args.args[1]["error"])


if __name__ == "__main__":
    unittest.main()
