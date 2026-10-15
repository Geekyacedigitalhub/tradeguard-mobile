import asyncio
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from app.ctrader_realized_metrics import realized_pl_for_utc_day


class Detail:
    def __init__(self, fee_present=True):
        self.moneyDigits = 2
        self.grossProfit = 1000
        self.swap = 0
        self.commission = -100
        self.pnlConversionFee = 0
        self.fee_present = fee_present

    def HasField(self, field):
        return field in {"moneyDigits", "grossProfit", "swap", "commission"} or (
            field == "pnlConversionFee" and self.fee_present
        )


def close_deal(ts, fee_present=True):
    return SimpleNamespace(
        dealId=7,
        executionTimestamp=ts,
        closePositionDetail=Detail(fee_present=fee_present),
    )


class RealizedMetricTests(unittest.TestCase):
    def test_uses_explicit_utc_day_window_and_preserves_provenance(self):
        calls = []
        async def fetch_page(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(hasMore=False, deal=[close_deal(kwargs["from_timestamp"] + 10)])

        result = asyncio.run(realized_pl_for_utc_day(
            fetch_page,
            account_id=42,
            as_of=datetime(2026, 10, 15, 12, 30, tzinfo=timezone.utc),
        ))
        self.assertEqual(calls[0]["from_timestamp"], 1792022400000)
        self.assertEqual(calls[0]["to_timestamp"], 1792067400001)
        self.assertEqual(result["realized_net_pnl"], 9.0)
        self.assertEqual(result["window_timezone"], "UTC")
        self.assertTrue(result["history_complete"])
        self.assertEqual(result["source"], "ctrader_close_deal_history")

    def test_missing_conversion_fee_withholds_daily_net_pnl(self):
        async def fetch_page(**kwargs):
            return SimpleNamespace(
                hasMore=False,
                deal=[close_deal(kwargs["from_timestamp"] + 10, fee_present=False)],
            )

        result = asyncio.run(realized_pl_for_utc_day(
            fetch_page,
            account_id=42,
            as_of=datetime(2026, 10, 15, 12, 30, tzinfo=timezone.utc),
        ))
        self.assertIsNone(result["realized_net_pnl"])
        self.assertIsNone(result["pnl_conversion_fee"])
        self.assertEqual(
            result["status"],
            "conversion_fee_unavailable_for_some_closing_deals",
        )

    def test_rejects_naive_datetime_and_live_environment(self):
        async def unused(**kwargs):
            raise AssertionError("should not fetch")
        with self.assertRaises(ValueError):
            asyncio.run(realized_pl_for_utc_day(
                unused, account_id=42, as_of=datetime(2026, 10, 15, 12, 30)
            ))
        with self.assertRaises(RuntimeError):
            asyncio.run(realized_pl_for_utc_day(
                unused, account_id=42, environment="live"
            ))


if __name__ == "__main__":
    unittest.main()
