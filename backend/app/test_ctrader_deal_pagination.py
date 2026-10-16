"""Regression tests for fail-closed cTrader deal-history pagination."""
import unittest
from types import SimpleNamespace

from .ctrader_deal_pagination import fetch_complete_deal_history


def deal(deal_id, timestamp):
    return SimpleNamespace(dealId=deal_id, executionTimestamp=timestamp)


class DealPaginationTests(unittest.IsolatedAsyncioTestCase):
    async def test_deduplicates_overlapping_pages_without_skipping_equal_timestamps(self):
        pages = iter([
            SimpleNamespace(deal=[deal(1, 100), deal(2, 101)], hasMore=True),
            SimpleNamespace(deal=[deal(2, 101), deal(3, 102)], hasMore=False),
        ])
        calls = []

        async def fetch_page(**kwargs):
            calls.append(kwargs)
            return next(pages)

        result = await fetch_complete_deal_history(
            fetch_page, account_id=7, from_timestamp=100, to_timestamp=200
        )
        self.assertEqual([item.dealId for item in result["deal"]], [1, 2, 3])
        self.assertEqual(result["pages_fetched"], 2)
        self.assertEqual(calls[1]["from_timestamp"], 101)

    async def test_rejects_out_of_window_deal(self):
        async def fetch_page(**kwargs):
            return SimpleNamespace(deal=[deal(1, 200)], hasMore=False)

        with self.assertRaisesRegex(RuntimeError, "outside the requested time window"):
            await fetch_complete_deal_history(
                fetch_page, account_id=7, from_timestamp=100, to_timestamp=200
            )

    async def test_rejects_pagination_without_stable_ids_when_more_pages_exist(self):
        async def fetch_page(**kwargs):
            return SimpleNamespace(
                deal=[SimpleNamespace(executionTimestamp=100)], hasMore=True
            )

        with self.assertRaisesRegex(RuntimeError, "without stable deal IDs"):
            await fetch_complete_deal_history(
                fetch_page, account_id=7, from_timestamp=100, to_timestamp=200
            )

    async def test_rejects_stalled_pagination(self):
        async def fetch_page(**kwargs):
            return SimpleNamespace(deal=[deal(1, 100)], hasMore=True)

        with self.assertRaisesRegex(RuntimeError, "pagination stalled"):
            await fetch_complete_deal_history(
                fetch_page, account_id=7, from_timestamp=100, to_timestamp=200
            )

    async def test_rejects_invalid_limits_and_live_environment(self):
        async def fetch_page(**kwargs):
            self.fail("fetch_page should not be called for invalid arguments")

        with self.assertRaises(ValueError):
            await fetch_complete_deal_history(
                fetch_page, account_id=True, from_timestamp=100, to_timestamp=200
            )
        with self.assertRaises(RuntimeError):
            await fetch_complete_deal_history(
                fetch_page, account_id=7, from_timestamp=100, to_timestamp=200,
                environment="live"
            )


if __name__ == "__main__":
    unittest.main()
