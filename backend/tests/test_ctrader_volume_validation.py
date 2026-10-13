import unittest

from app.ctrader_volume_validation import validate_protocol_volume, validate_symbol_volume_metadata


class CTraderProtocolVolumeValidationTests(unittest.TestCase):
    def test_accepts_positive_integer_protocol_volume(self):
        self.assertEqual(validate_protocol_volume(100), 100)
        self.assertEqual(validate_protocol_volume(2500, field="close volume"), 2500)

    def test_rejects_non_integer_or_non_positive_volume(self):
        for value in (0, -1, True, False, 100.0, 100.5, "100", None):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "positive broker protocol integer"):
                    validate_protocol_volume(value)

    def test_rejects_out_of_range_protocol_volume(self):
        with self.assertRaisesRegex(ValueError, "positive broker protocol integer"):
            validate_protocol_volume((1 << 63), field="close volume")

    def test_rejects_out_of_range_symbol_volume_metadata(self):
        max_id = (1 << 63) - 1
        invalid_sets = (
            (max_id + 1, max_id + 1, 1),
            (1, max_id + 1, 1),
            (1, max_id, max_id + 1),
        )
        for values in invalid_sets:
            with self.subTest(values=values):
                with self.assertRaisesRegex(ValueError, "positive broker protocol integer"):
                    validate_symbol_volume_metadata(*values)

    def test_accepts_valid_symbol_volume_metadata(self):
        self.assertEqual(validate_symbol_volume_metadata(100, 1000000, 100), (100, 1000000, 100))

    def test_rejects_coerced_or_non_positive_symbol_volume_metadata(self):
        invalid_sets = (
            (0, 1000, 100),
            (100, 0, 100),
            (100, 1000, 0),
            (True, 1000, 100),
            (100, 1000.0, 100),
            ("100", 1000, 100),
            (1000, 100, 100),
        )
        for values in invalid_sets:
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    validate_symbol_volume_metadata(*values)


if __name__ == "__main__":
    unittest.main()
