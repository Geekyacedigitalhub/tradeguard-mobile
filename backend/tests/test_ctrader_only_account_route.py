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
                "connected":True,"balance":1000,"equity":1000,"positions":None
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


if __name__=="__main__":
    unittest.main()
