import unittest
from types import SimpleNamespace

from app.ctrader_money import decode_money_value, decode_ctrader_equity_snapshot, validate_money_digits


class CTraderMoneyTests(unittest.TestCase):
    def test_decodes_money_using_broker_precision(self):
        self.assertEqual(decode_money_value(12345, 2), 123.45)
        self.assertEqual(decode_money_value(-25, 0), -25.0)

    def test_uses_explicit_fallback_when_precision_is_missing(self):
        self.assertEqual(validate_money_digits(None, fallback=3), 3)
        self.assertEqual(decode_money_value(1250, 3), 1.25)

    def test_rejects_invalid_precision(self):
        for digits in (None, True, False, -1, 13, 2.5, "2"):
            with self.subTest(digits=digits):
                with self.assertRaisesRegex(ValueError, "moneyDigits"):
                    validate_money_digits(digits)

    def test_rejects_malformed_or_non_finite_money(self):
        for value in (True, float("nan"), float("inf"), -float("inf"), "bad", "123.45", object()):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "monetary value"):
                    decode_money_value(value, 2)


    def test_decodes_cloud_equity_from_valid_broker_metrics(self):
        trader = SimpleNamespace(moneyDigits=2, balance=125050)
        pnl = SimpleNamespace(
            moneyDigits=2,
            positionUnrealizedPnL=[
                SimpleNamespace(netUnrealizedPnL=1250),
                SimpleNamespace(netUnrealizedPnL=-300),
            ],
        )
        self.assertEqual(decode_ctrader_equity_snapshot(trader, pnl), (1250.5, 1260.0))

    def test_rejects_missing_balance_instead_of_assuming_zero(self):
        trader = SimpleNamespace(moneyDigits=2)
        pnl = SimpleNamespace(moneyDigits=2, positionUnrealizedPnL=[])
        with self.assertRaisesRegex(ValueError, "balance"):
            decode_ctrader_equity_snapshot(trader, pnl)

    def test_rejects_missing_or_malformed_unrealized_positions(self):
        trader = SimpleNamespace(moneyDigits=2, balance=100000)
        for positions in (None, [SimpleNamespace()], [None]):
            with self.subTest(positions=positions):
                pnl = SimpleNamespace(moneyDigits=2, positionUnrealizedPnL=positions)
                with self.assertRaises(ValueError):
                    decode_ctrader_equity_snapshot(trader, pnl)

    def test_rejects_non_finite_unrealized_pnl_and_equity(self):
        trader = SimpleNamespace(moneyDigits=2, balance=100000)
        for value in (float("inf"), float("nan"), True):
            with self.subTest(value=value):
                pnl = SimpleNamespace(
                    moneyDigits=2,
                    positionUnrealizedPnL=[SimpleNamespace(netUnrealizedPnL=value)],
                )
                with self.assertRaises(ValueError):
                    decode_ctrader_equity_snapshot(trader, pnl)


if __name__ == "__main__":
    unittest.main()
