import unittest

from app.ctrader_volume_validation import validate_protocol_volume


class CTraderProtocolVolumeValidationTests(unittest.TestCase):
    def test_accepts_positive_integer_protocol_volume(self):
        self.assertEqual(validate_protocol_volume(100), 100)
        self.assertEqual(validate_protocol_volume(2500, field="close volume"), 2500)

    def test_rejects_non_integer_or_non_positive_volume(self):
        for value in (0, -1, True, False, 100.0, 100.5, "100", None):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "positive broker protocol integer"):
                    validate_protocol_volume(value)


if __name__ == "__main__":
    unittest.main()
