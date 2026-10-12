import unittest

from app.ctrader_volume import validate_protocol_volume


class CTraderVolumeValidationTests(unittest.TestCase):
    def setUp(self):
        self.constraints = {"min_volume": 1000, "max_volume": 10000, "step_volume": 1000}

    def test_accepts_minimum_maximum_and_step_aligned_values(self):
        for volume in (1000, 2000, 5000, 10000):
            with self.subTest(volume=volume):
                self.assertEqual(validate_protocol_volume(volume, self.constraints), volume)

    def test_rejects_below_minimum_and_above_maximum(self):
        for volume in (999, 11000):
            with self.subTest(volume=volume):
                with self.assertRaisesRegex(RuntimeError, "outside the allowed range"):
                    validate_protocol_volume(volume, self.constraints)

    def test_step_is_measured_from_minimum_not_zero(self):
        constraints = {"min_volume": 1500, "max_volume": 5500, "step_volume": 1000}
        self.assertEqual(validate_protocol_volume(1500, constraints), 1500)
        self.assertEqual(validate_protocol_volume(2500, constraints), 2500)
        with self.assertRaisesRegex(RuntimeError, "minimum/step"):
            validate_protocol_volume(2000, constraints)

    def test_rejects_incomplete_or_invalid_constraints(self):
        for constraints in (
            {},
            {"min_volume": 1000, "max_volume": 500, "step_volume": 100},
            {"min_volume": 1000, "max_volume": 5000, "step_volume": 0},
            {"min_volume": "invalid", "max_volume": 5000, "step_volume": 100},
            {"min_volume": 1000.5, "max_volume": 5000, "step_volume": 100},
            {"min_volume": True, "max_volume": 5000, "step_volume": 100},
        ):
            with self.subTest(constraints=constraints):
                with self.assertRaises(RuntimeError):
                    validate_protocol_volume(1000, constraints)

    def test_rejects_non_integer_or_non_positive_volume(self):
        for volume in (0, -1000, True, 1000.5, "1000"):
            with self.subTest(volume=volume):
                with self.assertRaises(RuntimeError):
                    validate_protocol_volume(volume, self.constraints)


if __name__ == "__main__":
    unittest.main()
