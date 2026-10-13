import unittest
from unittest.mock import AsyncMock, patch

from app import market_data


class CloudOnlyMarketDataTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_user_id_does_not_trigger_desktop_bridge_fallback(self):
        with (
            patch.object(market_data, "_stored_cloud_candles", return_value=None),
            patch.object(
                market_data,
                "_cloud_provider_candles",
                new=AsyncMock(side_effect=RuntimeError("cloud provider unavailable")),
            ),
            patch.object(
                market_data,
                "connection",
                side_effect=AssertionError("market-data lookup must not query the desktop bridge table"),
            ) as db_connection,
        ):
            with self.assertRaisesRegex(RuntimeError, "Cloud market data unavailable"):
                await market_data.candles_for(
                    symbol="EURUSD",
                    interval="5m",
                    limit=60,
                    user_id="legacy-user-id",
                )

        db_connection.assert_not_called()


if __name__ == "__main__":
    unittest.main()
