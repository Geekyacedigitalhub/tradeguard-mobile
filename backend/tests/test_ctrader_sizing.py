import unittest

from app.ctrader_sizing import calculate_protocol_volume


class CTraderRiskSizingTests(unittest.TestCase):
    def setUp(self):
        self.constraints = {"min_volume": 100, "max_volume": 100000, "step_volume": 100}

    def size(self, **overrides):
        values = {
            "risk_amount": 10.0,
            "stop_distance": 0.5,
            "account_currency_loss_per_price_unit_per_traded_unit": 0.2,
            "constraints": self.constraints,
        }
        values.update(overrides)
        return calculate_protocol_volume(**values)

    def test_calculates_protocol_volume_and_estimated_risk(self):
        result = self.size()
        self.assertEqual(result["protocol_volume"], 10000)
        self.assertEqual(result["traded_units"], 100.0)
        self.assertAlmostEqual(result["estimated_risk"], 10.0)

    def test_rounds_down_to_broker_step_without_exceeding_risk(self):
        result = self.size(risk_amount=10.09)
        self.assertEqual(result["protocol_volume"] % 100, 0)
        self.assertLessEqual(result["estimated_risk"], 10.09)

    def test_aligns_from_minimum_volume(self):
        constraints = {"min_volume": 150, "max_volume": 10000, "step_volume": 100}
        result = self.size(constraints=constraints, risk_amount=0.4)
        self.assertEqual(result["protocol_volume"], 350)
        self.assertLessEqual(result["estimated_risk"], 0.4)

    def test_rejects_too_small_risk_and_above_maximum(self):
        with self.assertRaisesRegex(ValueError, "too small"):
            self.size(risk_amount=0.01)
        with self.assertRaisesRegex(ValueError, "above the broker maximum"):
            self.size(risk_amount=1000)

    def test_rejects_missing_or_invalid_currency_conversion(self):
        for value in (None, 0, -1, float("nan"), float("inf")):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.size(account_currency_loss_per_price_unit_per_traded_unit=value)

    def test_rejects_invalid_risk_inputs_and_constraints(self):
        for value in (0, -1, float("nan"), float("inf")):
            with self.subTest(risk=value):
                with self.assertRaises(ValueError):
                    self.size(risk_amount=value)
        with self.assertRaises(ValueError):
            self.size(constraints={})
        for malformed in (
            {"min_volume": 100.5, "max_volume": 100000, "step_volume": 100},
            {"min_volume": True, "max_volume": 100000, "step_volume": 100},
            {"min_volume": "100", "max_volume": 100000, "step_volume": 100},
        ):
            with self.subTest(constraints=malformed):
                with self.assertRaisesRegex(ValueError, "integer protocol values"):
                    self.size(constraints=malformed)


if __name__ == "__main__":
    unittest.main()
