import unittest
from types import SimpleNamespace

from app.ctrader_pnl import calculate_realized_pnl, calculate_unrealized_pnl_by_position


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


    def test_rejects_non_finite_or_malformed_monetary_values(self):
        for value in (float("nan"), float("inf"), -float("inf"), "not-a-number", True):
            with self.subTest(value=value):
                deal = SimpleNamespace(
                    closePositionDetail=SimpleNamespace(grossProfit=value, moneyDigits=2)
                )
                with self.assertRaisesRegex(ValueError, "monetary value"):
                    calculate_realized_pnl([deal])

    def test_rejects_invalid_money_digits_types(self):
        for digits in (True, 2.5, "2", -1, 13):
            with self.subTest(digits=digits):
                deal = SimpleNamespace(
                    closePositionDetail=SimpleNamespace(grossProfit=500, moneyDigits=digits)
                )
                with self.assertRaisesRegex(ValueError, "moneyDigits"):
                    calculate_realized_pnl([deal])

    def test_rejects_invalid_money_digits(self):
        deal = SimpleNamespace(closePositionDetail=SimpleNamespace(grossProfit=500, moneyDigits=99))
        with self.assertRaisesRegex(ValueError, "moneyDigits"):
            calculate_realized_pnl([deal])


if __name__ == "__main__":
    unittest.main()



class CTraderUnrealizedPnlTests(unittest.TestCase):
    def test_maps_scaled_broker_pnl_to_position_id(self):
        rows = [
            SimpleNamespace(positionId=11, netUnrealizedPnL=1234),
            SimpleNamespace(positionId=12, netUnrealizedPnL=-250),
        ]
        self.assertEqual(
            calculate_unrealized_pnl_by_position(rows, money_digits=2),
            {11: 12.34, 12: -2.5},
        )

    def test_ignores_rows_without_valid_position_id(self):
        rows = [
            SimpleNamespace(positionId=0, netUnrealizedPnL=100),
            SimpleNamespace(positionId=None, netUnrealizedPnL=200),
            SimpleNamespace(positionId=3, netUnrealizedPnL=300),
        ]
        self.assertEqual(
            calculate_unrealized_pnl_by_position(rows, money_digits=2),
            {3: 3.0},
        )

    def test_rejects_invalid_money_digits_and_pnl(self):
        with self.assertRaisesRegex(ValueError, "moneyDigits"):
            calculate_unrealized_pnl_by_position([], money_digits=True)
        for raw in (True, "12", float("nan"), float("inf")):
            with self.subTest(raw=raw):
                rows = [SimpleNamespace(positionId=11, netUnrealizedPnL=raw)]
                with self.assertRaisesRegex(ValueError, "unrealized P/L"):
                    calculate_unrealized_pnl_by_position(rows, money_digits=2)
