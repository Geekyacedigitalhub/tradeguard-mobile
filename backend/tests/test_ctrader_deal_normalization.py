import unittest
from types import SimpleNamespace

from app.ctrader_deal_history import normalize_close_deal


class ProtoLikeDetail:
    def __init__(self, **values):
        self._values = values
        for key, value in values.items():
            setattr(self, key, value)

    def HasField(self, name):
        return name in self._values


class CTraderDealNormalizationTests(unittest.TestCase):
    def test_scales_signed_components_and_preserves_conversion_fee(self):
        detail = ProtoLikeDetail(
            moneyDigits=2,
            grossProfit=12345,
            swap=-125,
            commission=-250,
            pnlConversionFee=-10,
        )
        result = normalize_close_deal(SimpleNamespace(closePositionDetail=detail))

        self.assertEqual(result, {
            "money_digits": 2,
            "gross_profit": 123.45,
            "swap": -1.25,
            "commission": -2.5,
            "pnl_conversion_fee": -0.1,
        })

    def test_missing_optional_conversion_fee_stays_unknown(self):
        detail = ProtoLikeDetail(
            moneyDigits=2,
            grossProfit=100,
            swap=0,
            commission=0,
        )
        result = normalize_close_deal(SimpleNamespace(closePositionDetail=detail))
        self.assertIsNone(result["pnl_conversion_fee"])

    def test_rejects_non_close_deal_and_missing_precision(self):
        with self.assertRaises(ValueError):
            normalize_close_deal(SimpleNamespace())

        detail = ProtoLikeDetail(grossProfit=100, swap=0, commission=0)
        with self.assertRaises(ValueError):
            normalize_close_deal(SimpleNamespace(closePositionDetail=detail))

    def test_rejects_invalid_money_digits_and_required_components(self):
        for digits in (-1, 9):
            with self.subTest(digits=digits):
                detail = ProtoLikeDetail(
                    moneyDigits=digits,
                    grossProfit=100,
                    swap=0,
                    commission=0,
                )
                with self.assertRaises(ValueError):
                    normalize_close_deal(SimpleNamespace(closePositionDetail=detail))

        detail = ProtoLikeDetail(moneyDigits=2, grossProfit=100, swap=0)
        with self.assertRaises(ValueError):
            normalize_close_deal(SimpleNamespace(closePositionDetail=detail))


if __name__ == "__main__":
    unittest.main()
