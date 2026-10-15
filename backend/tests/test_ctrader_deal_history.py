import asyncio
import unittest
from unittest.mock import AsyncMock

from app import ctrader_service


class CTraderDealHistoryTests(unittest.TestCase):
    def test_deal_history_request_is_bounded_and_demo_only(self):
        if ctrader_service.ProtoOADealListReq is None:
            self.skipTest("cTrader Open API SDK is unavailable")
        manager = ctrader_service.CTraderManager()
        manager._send = AsyncMock(return_value="broker-response")

        result = asyncio.run(
            manager.deals(
                account_id=1234,
                from_timestamp=1_800_000_000_000,
                to_timestamp=1_800_086_400_000,
                environment="demo",
                max_rows=500,
            )
        )

        self.assertEqual(result, "broker-response")
        manager._send.assert_awaited_once()
        environment, request = manager._send.await_args.args[:2]
        self.assertEqual(environment, "demo")
        self.assertEqual(request.ctidTraderAccountId, 1234)
        self.assertEqual(request.fromTimestamp, 1_800_000_000_000)
        self.assertEqual(request.toTimestamp, 1_800_086_400_000)
        self.assertEqual(request.maxRows, 500)

    def test_deal_history_rejects_invalid_windows_and_live_environment(self):
        manager = ctrader_service.CTraderManager()
        manager._send = AsyncMock()

        cases = (
            {"account_id": 1234, "from_timestamp": 100, "to_timestamp": 100},
            {"account_id": 1234, "from_timestamp": 101, "to_timestamp": 100},
            {"account_id": 1234, "from_timestamp": 1, "to_timestamp": 2, "max_rows": 1001},
            {"account_id": 1234, "from_timestamp": 1, "to_timestamp": 2, "environment": "live"},
            {"account_id": 1234, "from_timestamp": 1.5, "to_timestamp": 2},
        )
        for kwargs in cases:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises((ValueError, RuntimeError)):
                    asyncio.run(manager.deals(**kwargs))

        manager._send.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
