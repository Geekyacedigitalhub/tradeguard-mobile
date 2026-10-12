import unittest
from types import SimpleNamespace

from app.ctrader_pnl import calculate_realized_pnl


class CTraderRealizedPnlTests(unittest.TestCase):
    def test_scales_money_fields_and_applies_costs(self):
        deals = [
            SimpleNamespace(
                moneyDigits=2,
                closePositionDetail=SimpleNamespace(
                    grossProfit=1234,
                    swap=-25,
                    commission=-10,
                    pnlConversionFee=9,
                    moneyDigits=2,
                ),
            )
        ]
        self.assertAlmostEqual(calculate_realized_pnl(deals), 11.90)

    def test_uses_deal_digits_when_detail_digits_are_missing(self):
        deal = SimpleNamespace(
            moneyDigits=3,
            closePositionDetail=SimpleNamespace(grossProfit=1250),
        )
        self.assertAlmostEqual(calculate_realized_pnl([deal]), 1.25)

    def test_ignores_deals_without_closed_position_detail(self):
        deals = [
            SimpleNamespace(closePositionDetail=None),
            SimpleNamespace(closePositionDetail=SimpleNamespace(grossProfit=500, moneyDigits=2)),
        ]
        self.assertAlmostEqual(calculate_realized_pnl(deals), 5.0)

    def test_truncated_history_is_unavailable_not_partial(self):
        deal = SimpleNamespace(closePositionDetail=SimpleNamespace(grossProfit=500, moneyDigits=2))
        self.assertIsNone(calculate_realized_pnl([deal], has_more=True))

    def test_rejects_invalid_money_digits(self):
        deal = SimpleNamespace(closePositionDetail=SimpleNamespace(grossProfit=500, moneyDigits=99))
        with self.assertRaisesRegex(ValueError, "moneyDigits"):
            calculate_realized_pnl([deal])


if __name__ == "__main__":
    unittest.main()
