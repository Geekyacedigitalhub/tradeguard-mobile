import unittest

from app.ctrader_worker import _validate_broker_volume


class CTraderWorkerVolumeSafetyTests(unittest.TestCase):
    def test_accepts_volume_aligned_to_minimum_offset_step(self):
        _validate_broker_volume(250, min_volume=150, max_volume=1000, step_volume=100)

    def test_rejects_volume_below_minimum(self):
        with self.assertRaisesRegex(RuntimeError, "min/max/step constraints"):
            _validate_broker_volume(100, min_volume=150, max_volume=1000, step_volume=100)

    def test_rejects_volume_above_maximum(self):
        with self.assertRaisesRegex(RuntimeError, "min/max/step constraints"):
            _validate_broker_volume(1050, min_volume=150, max_volume=1000, step_volume=100)

    def test_rejects_volume_not_aligned_to_minimum_offset_step(self):
        with self.assertRaisesRegex(RuntimeError, "min/max/step constraints"):
            _validate_broker_volume(200, min_volume=150, max_volume=1000, step_volume=100)

    def test_rejects_missing_or_invalid_broker_limits(self):
        for limits in (
            (0, 1000, 100),
            (100, 50, 10),
            (100, 1000, 0),
        ):
            with self.subTest(limits=limits), self.assertRaisesRegex(
                RuntimeError, "full-symbol volume limits"
            ):
                _validate_broker_volume(100, *limits)


if __name__ == "__main__":
    unittest.main()
