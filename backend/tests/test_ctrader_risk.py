import unittest

from app.ctrader_risk import calculate_verified_volume


class CTraderRiskSizingTests(unittest.TestCase):
    def valid_inputs(self):
        return {
            "risk_amount": 100.0,
            "stop_distance": 2.0,
            "account_currency_loss_per_price_unit_per_lot": 10.0,
            "lot_size": 100000,
            "min_volume": 100,
            "max_volume": 100000000,
            "step_volume": 100,
        }

    def test_calculates_volume_rounding_down_to_broker_step(self):
        result = calculate_verified_volume(**self.valid_inputs())
        self.assertEqual(result["broker_volume"] % 100, 0)
        self.assertLessEqual(result["estimated_loss_at_stop"], 100.0)
        self.assertTrue(result["broker_volume_verified"])

    def test_rejects_missing_or_nonpositive_risk_inputs(self):
        for field in ("risk_amount", "stop_distance", "account_currency_loss_per_price_unit_per_lot"):
            inputs = self.valid_inputs()
            inputs[field] = 0
            with self.subTest(field=field), self.assertRaises(ValueError):
                calculate_verified_volume(**inputs)

    def test_rejects_invalid_broker_metadata(self):
        inputs = self.valid_inputs()
        inputs["step_volume"] = 0
        with self.assertRaises(ValueError):
            calculate_verified_volume(**inputs)

    def test_rejects_when_risk_is_below_minimum_volume(self):
        inputs = self.valid_inputs()
        inputs["risk_amount"] = 0.00001
        with self.assertRaises(ValueError):
            calculate_verified_volume(**inputs)

    def test_never_rounds_up_above_risk_cap(self):
        inputs = self.valid_inputs()
        inputs["risk_amount"] = 101.0
        result = calculate_verified_volume(**inputs)
        self.assertLessEqual(result["estimated_loss_at_stop"], inputs["risk_amount"])


if __name__ == "__main__":
    unittest.main()
