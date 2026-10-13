import unittest
from types import SimpleNamespace

from app.ctrader_close_verification import (
    classify_close_result,
    classify_protection_result,
    position_volume_snapshot,
    protection_snapshot,
)


def reconcile(*positions):
    return SimpleNamespace(position=list(positions))


def position(position_id, volume, stop_loss=None, take_profit=None):
    return SimpleNamespace(
        positionId=position_id,
        tradeData=SimpleNamespace(volume=volume),
        stopLoss=stop_loss,
        takeProfit=take_profit,
    )


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

    def test_disappeared_position_after_partial_close_is_not_confirmed_as_full_close(self):
        self.assertEqual(classify_close_result(500, 200, None), "changed_unexpectedly")

    def test_does_not_claim_success_when_state_does_not_match(self):
        self.assertEqual(classify_close_result(500, 200, 500), "unconfirmed")
        self.assertEqual(classify_close_result(500, 200, 600), "changed_unexpectedly")
        self.assertEqual(classify_close_result(500, 200, 250), "changed_unexpectedly")

    def test_rejects_close_volume_above_open_volume(self):
        with self.assertRaises(ValueError):
            classify_close_result(100, 200, None)

    def test_reads_broker_reported_stop_loss_and_take_profit(self):
        snapshot = protection_snapshot(reconcile(position(12, 500, 1.234, 1.250)), 12)
        self.assertEqual(snapshot, {"stop_loss": 1.234, "take_profit": 1.250})

    def test_missing_position_returns_none_for_protection_snapshot(self):
        self.assertIsNone(protection_snapshot(reconcile(position(13, 500)), 12))

    def test_confirms_protection_only_when_requested_values_match_broker_state(self):
        before = {"stop_loss": None, "take_profit": None}
        after = {"stop_loss": 1.234, "take_profit": 1.250}
        self.assertEqual(
            classify_protection_result(before, 1.234, 1.250, after),
            "confirmed_protected",
        )

    def test_single_field_amendment_must_preserve_other_protection(self):
        before = {"stop_loss": 1.100, "take_profit": 1.300}
        self.assertEqual(
            classify_protection_result(
                before, 1.150, None,
                {"stop_loss": 1.150, "take_profit": None},
            ),
            "take_profit_unconfirmed",
        )
        self.assertEqual(
            classify_protection_result(
                before, None, 1.350,
                {"stop_loss": None, "take_profit": 1.350},
            ),
            "stop_loss_unconfirmed",
        )

    def test_stop_loss_and_take_profit_mismatch_are_unconfirmed(self):
        before = {"stop_loss": None, "take_profit": None}
        self.assertEqual(
            classify_protection_result(before, 1.234, None, {"stop_loss": None, "take_profit": None}),
            "stop_loss_unconfirmed",
        )
        self.assertEqual(
            classify_protection_result(before, None, 1.250, {"stop_loss": None, "take_profit": 1.240}),
            "take_profit_unconfirmed",
        )

    def test_protection_verification_fails_closed_for_missing_position(self):
        self.assertEqual(
            classify_protection_result(
                {"stop_loss": None, "take_profit": None}, 1.234, None, None
            ),
            "position_missing_after_amendment",
        )
        with self.assertRaises(ValueError):
            classify_protection_result(None, 1.234, None, {"stop_loss": 1.234, "take_profit": None})


if __name__ == "__main__":
    unittest.main()
