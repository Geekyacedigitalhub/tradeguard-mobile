import unittest
from types import SimpleNamespace

from app.ctrader_deal_history import summarize_realized_close_deals


class ProtoLikeDetail:
    def __init__(self, **values):
        self._values = values
        for key, value in values.items():
            setattr(self, key, value)

    def HasField(self, name):
        return name in self._values


def closing_deal(timestamp, gross, swap, commission, fee=None):
    values = {
        "moneyDigits": 2,
        "grossProfit": gross,
        "swap": swap,
        "commission": commission,
    }
    if fee is not None:
        values["pnlConversionFee"] = fee
    return SimpleNamespace(
        executionTimestamp=timestamp,
        closePositionDetail=ProtoLikeDetail(**values),
    )


class CTraderRealizedHistoryTests(unittest.TestCase):
    def test_sums_close_components_from_complete_broker_window(self):
        response = SimpleNamespace(
            hasMore=False,
            deal=[
                closing_deal(150, 1000, -100, -50, -10),
                closing_deal(250, -200, 0, -25),
                # A non-closing deal is not realized P/L.
                SimpleNamespace(executionTimestamp=275),
            ],
        )
        result = summarize_realized_close_deals(response, 100, 300)

        self.assertEqual(result["close_deals_count"], 2)
        self.assertEqual(result["gross_profit"], 8.0)
        self.assertEqual(result["swap"], -1.0)
        self.assertEqual(result["commission"], -0.75)
        self.assertEqual(result["pnl_conversion_fee"], -0.1)
        self.assertAlmostEqual(result["realized_net_pnl"], 6.15)
        self.assertEqual(result["status"], "broker_close_deal_components_summed")

    def test_refuses_partial_history_and_out_of_window_closing_deal(self):
        partial = SimpleNamespace(hasMore=True, deal=[closing_deal(150, 100, 0, 0)])
        with self.assertRaises(ValueError):
            summarize_realized_close_deals(partial, 100, 300)

        outside = SimpleNamespace(hasMore=False, deal=[closing_deal(300, 100, 0, 0)])
        with self.assertRaises(ValueError):
            summarize_realized_close_deals(outside, 100, 300)

    def test_no_closing_deals_remains_unknown_not_zero(self):
        response = SimpleNamespace(hasMore=False, deal=[SimpleNamespace(executionTimestamp=150)])
        result = summarize_realized_close_deals(response, 100, 300)
        self.assertIsNone(result["realized_net_pnl"])
        self.assertEqual(result["status"], "no_closing_deals_in_window")

    def test_rejects_invalid_window(self):
        with self.assertRaises(ValueError):
            summarize_realized_close_deals(
                SimpleNamespace(hasMore=False, deal=[]), 200, 200
            )


if __name__ == "__main__":
    unittest.main()
