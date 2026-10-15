import unittest
from types import SimpleNamespace

from app.ctrader_deal_fee_validation import summarize_realized_close_deals_with_fee_check


class Detail:
    def __init__(self, fee_present, fee=0):
        self.moneyDigits = 2
        self.grossProfit = 1000
        self.swap = 0
        self.commission = -100
        self.pnlConversionFee = fee
        self.fee_present = fee_present

    def HasField(self, field):
        return field in {"moneyDigits", "grossProfit", "swap", "commission"} or (
            field == "pnlConversionFee" and self.fee_present
        )


def deal(ts, fee_present, fee=0):
    return SimpleNamespace(
        dealId=1,
        executionTimestamp=ts,
        closePositionDetail=Detail(fee_present, fee),
    )


class FeeValidationTests(unittest.TestCase):
    def test_missing_optional_conversion_fee_withholds_net_pnl(self):
        response = SimpleNamespace(hasMore=False, deal=[deal(150, False)])
        result = summarize_realized_close_deals_with_fee_check(response, 100, 200)
        self.assertIsNone(result["pnl_conversion_fee"])
        self.assertIsNone(result["realized_net_pnl"])
        self.assertEqual(
            result["status"],
            "conversion_fee_unavailable_for_some_closing_deals",
        )
        self.assertEqual(result["gross_profit"], 10.0)
        self.assertEqual(result["commission"], -1.0)

    def test_one_missing_fee_withholds_net_pnl_for_mixed_history(self):
        response = SimpleNamespace(
            hasMore=False,
            deal=[deal(150, True, -25), deal(160, False)],
        )
        result = summarize_realized_close_deals_with_fee_check(response, 100, 200)
        self.assertEqual(result["close_deals_count"], 2)
        self.assertIsNone(result["pnl_conversion_fee"])
        self.assertIsNone(result["realized_net_pnl"])
        self.assertEqual(
            result["status"],
            "conversion_fee_unavailable_for_some_closing_deals",
        )

    def test_present_conversion_fee_keeps_calculated_net_pnl(self):
        response = SimpleNamespace(hasMore=False, deal=[deal(150, True, -25)])
        result = summarize_realized_close_deals_with_fee_check(response, 100, 200)
        self.assertEqual(result["pnl_conversion_fee"], -0.25)
        self.assertEqual(result["realized_net_pnl"], 8.75)
        self.assertEqual(result["status"], "broker_close_deal_components_summed")


if __name__ == "__main__":
    unittest.main()
