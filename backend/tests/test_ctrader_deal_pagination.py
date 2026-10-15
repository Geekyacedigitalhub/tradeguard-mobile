import asyncio
import unittest
from types import SimpleNamespace

from app.ctrader_deal_pagination import fetch_complete_deal_history


def d(i, ts):
    return SimpleNamespace(dealId=i, executionTimestamp=ts)


class PaginationTests(unittest.TestCase):
    def test_same_timestamp_overlap_is_deduplicated_without_skipping(self):
        pages = [
            SimpleNamespace(hasMore=True, deal=[d(1, 100), d(2, 200)]),
            SimpleNamespace(hasMore=False, deal=[d(2, 200), d(3, 200)]),
        ]
        calls = []

        async def fetch_page(**kwargs):
            calls.append(kwargs)
            return pages.pop(0)

        result = asyncio.run(fetch_complete_deal_history(
            fetch_page, account_id=42, from_timestamp=100, to_timestamp=300, max_rows=2
        ))
        self.assertEqual([x.dealId for x in result["deal"]], [1, 2, 3])
        self.assertEqual(calls[1]["from_timestamp"], 200)

    def test_stalled_or_unidentifiable_pages_fail_closed(self):
        async def stalled(**kwargs):
            return SimpleNamespace(hasMore=True, deal=[d(1, 100)])

        with self.assertRaises(RuntimeError):
            asyncio.run(fetch_complete_deal_history(
                stalled, account_id=42, from_timestamp=100, to_timestamp=300
            ))

        async def no_ids(**kwargs):
            return SimpleNamespace(hasMore=True, deal=[SimpleNamespace(executionTimestamp=100)])

        with self.assertRaises(RuntimeError):
            asyncio.run(fetch_complete_deal_history(
                no_ids, account_id=42, from_timestamp=100, to_timestamp=300
            ))

    def test_rejects_oversized_or_out_of_window_pages(self):
        async def oversized(**kwargs):
            return SimpleNamespace(hasMore=False, deal=[d(1, 100), d(2, 101)])

        with self.assertRaises(RuntimeError):
            asyncio.run(fetch_complete_deal_history(
                oversized, account_id=42, from_timestamp=100, to_timestamp=300, max_rows=1
            ))

        async def outside(**kwargs):
            return SimpleNamespace(hasMore=False, deal=[d(1, 300)])

        with self.assertRaises(RuntimeError):
            asyncio.run(fetch_complete_deal_history(
                outside, account_id=42, from_timestamp=100, to_timestamp=300
            ))

        async def missing_timestamp(**kwargs):
            return SimpleNamespace(hasMore=False, deal=[SimpleNamespace(dealId=1)])

        with self.assertRaises(RuntimeError):
            asyncio.run(fetch_complete_deal_history(
                missing_timestamp, account_id=42, from_timestamp=100, to_timestamp=300
            ))

    def test_demo_and_limits_are_enforced(self):
        async def unused(**kwargs):
            raise AssertionError("request should not be made")

        with self.assertRaises(RuntimeError):
            asyncio.run(fetch_complete_deal_history(
                unused, account_id=42, from_timestamp=100, to_timestamp=300, environment="live"
            ))
        with self.assertRaises(ValueError):
            asyncio.run(fetch_complete_deal_history(
                unused, account_id=42, from_timestamp=100, to_timestamp=300, max_rows=1001
            ))


if __name__ == "__main__":
    unittest.main()
