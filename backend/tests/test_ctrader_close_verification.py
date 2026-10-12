import unittest
from types import SimpleNamespace

from app.ctrader_close_verification import classify_close_result, position_volume_snapshot


def reconcile(*positions):
    return SimpleNamespace(position=list(positions))


def position(position_id, volume):
    return SimpleNamespace(positionId=position_id, tradeData=SimpleNamespace(volume=volume))


class CTraderCloseVerificationTests(unittest.TestCase):
    def test_reads_broker_position_volume(self):
        self.assertEqual(position_volume_snapshot(reconcile(position(12, 500)), 12), 500)

    def test_returns_none_when_position_is_absent(self):
        self.assertIsNone(position_volume_snapshot(reconcile(position(13, 500)), 12))

    def test_rejects_invalid_or_duplicate_position_volume(self):
        for response in (
            reconcile(position(12, 0)),
            reconcile(position(12, 500), position(12, 300)),
        ):
            with self.subTest(response=response):
                with self.assertRaises(ValueError):
                    position_volume_snapshot(response, 12)

    def test_classifies_full_close(self):
        self.assertEqual(classify_close_result(500, 500, None), "confirmed_closed")

    def test_classifies_exact_partial_close(self):
        self.assertEqual(classify_close_result(500, 200, 300), "confirmed_reduced")

    def test_does_not_claim_success_when_state_does_not_match(self):
        self.assertEqual(classify_close_result(500, 200, 500), "unconfirmed")
        self.assertEqual(classify_close_result(500, 200, 250), "changed_unexpectedly")

    def test_rejects_close_volume_above_open_volume(self):
        with self.assertRaises(ValueError):
            classify_close_result(100, 200, None)


if __name__ == "__main__":
    unittest.main()
