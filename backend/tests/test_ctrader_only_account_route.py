import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app import main


class CTraderOnlyAccountRouteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        main._account_route_cache.clear()
        self.user={"id":"account-route-user"}

    async def test_unselected_ctrader_account_never_falls_back_to_legacy_metrics(self):
        with (
            patch("app.main.connection") as connection,
            patch("app.main.live_account_metrics") as legacy_metrics,
            patch("app.main.mt5_connected") as legacy_connected,
            patch("app.main.list_positions") as internal_positions,
        ):
            connection.return_value.__enter__.return_value.execute.return_value.fetchone.return_value=None
            with self.assertRaises(HTTPException) as caught:
                await main.account(self.user)

        self.assertEqual(caught.exception.status_code,409)
        legacy_metrics.assert_not_called()
        legacy_connected.assert_not_called()
        internal_positions.assert_not_called()

    async def test_missing_broker_positions_does_not_become_false_zero(self):
        with (
            patch("app.main.connection") as connection,
            patch("app.main.get_ctrader_account_snapshot", new=AsyncMock(return_value={
                "connected":True,"account_id":12345,"environment":"demo",
                "balance":1000,"equity":1000,"positions":None
            })),
            patch("app.main.live_account_metrics") as legacy_metrics,
        ):
            conn=connection.return_value.__enter__.return_value
            conn.execute.return_value.fetchone.return_value=(12345,"demo")
            with self.assertRaises(HTTPException) as caught:
                await main.account(self.user)

        self.assertEqual(caught.exception.status_code,503)
        self.assertIn("positions list",caught.exception.detail)
        legacy_metrics.assert_not_called()

    async def test_selected_live_snapshot_exposes_verified_broker_balance_and_positions(self):
        snapshot_value={
            "connected":True,"account_id":24680,"environment":"live",
            "balance":1250.5,"equity":1274.75,"today_pl":24.25,
            "drawdown":1.2,"currency":"USD",
            "positions":[{"position_id":91},{"position_id":92}],
        }
        with (
            patch("app.main.connection") as connection,
            patch("app.main.get_ctrader_account_snapshot", new=AsyncMock(return_value=snapshot_value)) as snapshot,
            patch("app.main.live_account_metrics") as legacy_metrics,
            patch("app.main.mt5_connected") as legacy_connected,
            patch("app.main.list_positions") as internal_positions,
        ):
            conn=connection.return_value.__enter__.return_value
            conn.execute.return_value.fetchone.side_effect=[
                (24680,"live"),
                (False,0.01,2.0,5,10.0),
            ]
            result=await main.account(self.user)

        self.assertEqual(result["balance"],1250.5)
        self.assertEqual(result["equity"],1274.75)
        self.assertEqual(result["currency"],"USD")
        self.assertEqual(result["bot"]["open_trades"],2)
        snapshot.assert_awaited_once_with(self.user)
        legacy_metrics.assert_not_called()
        legacy_connected.assert_not_called()
        internal_positions.assert_not_called()

    async def test_snapshot_for_different_selected_account_is_rejected_and_not_cached(self):
        with (
            patch("app.main.connection") as connection,
            patch("app.main.get_ctrader_account_snapshot", new=AsyncMock(return_value={
                "connected":True,"account_id":67890,"environment":"live",
                "balance":9000,"equity":9000,"positions":[]
            })) as snapshot,
        ):
            conn=connection.return_value.__enter__.return_value
            conn.execute.return_value.fetchone.return_value=(12345,"demo")
            with self.assertRaises(HTTPException) as caught:
                await main.account(self.user)

        self.assertEqual(caught.exception.status_code,503)
        self.assertIn("selection changed",caught.exception.detail)
        self.assertEqual(snapshot.await_count,1)
        self.assertFalse(any(key.startswith(self.user["id"]+":ctrader:12345:demo") for key in main._account_route_cache))


if __name__=="__main__":
    unittest.main()
