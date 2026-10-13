import unittest
from types import SimpleNamespace

from app.ctrader_close_verification import (
    classify_close_result,
    classify_protection_result,
    broker_outcome_is_confirmed,
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

    def test_rejects_duplicate_broker_positions_for_protection_snapshot(self):
        response = reconcile(
            position(12, 500, 1.100, 1.300),
            position(12, 400, 1.150, 1.350),
        )
        with self.assertRaisesRegex(ValueError, "duplicate"):
            protection_snapshot(response, 12)

    def test_ignores_unrelated_positions_when_reading_protection_snapshot(self):
        response = reconcile(
            position(13, 500, 1.100, 1.300),
            position(12, 400, 1.150, 1.350),
        )
        self.assertEqual(
            protection_snapshot(response, 12),
            {"stop_loss": 1.150, "take_profit": 1.350},
        )

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

    def test_protection_verification_rejects_coerced_or_non_finite_prices(self):
        before = {"stop_loss": None, "take_profit": None}
        invalid_values = (True, "1.234", float("nan"), float("inf"), 0, -1)
        for value in invalid_values:
            with self.subTest(requested=value):
                self.assertNotEqual(
                    classify_protection_result(before, value, None, {"stop_loss": value, "take_profit": None}),
                    "confirmed_protected",
                )
            with self.subTest(actual=value):
                self.assertNotEqual(
                    classify_protection_result(before, 1.234, None, {"stop_loss": value, "take_profit": None}),
                    "confirmed_protected",
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


class BrokerOutcomeEvidenceTests(unittest.TestCase):
    def test_full_close_requires_consistent_before_and_after_evidence(self):
        valid = {
            "status": "confirmed_closed",
            "volume_before": 500,
            "requested_close_volume": 500,
            "volume_after": None,
        }
        self.assertTrue(broker_outcome_is_confirmed("close_position", "completed", valid))
        for invalid in (
            {**valid, "volume_after": 1},
            {**valid, "requested_close_volume": 200},
            {k: v for k, v in valid.items() if k != "volume_after"},
            {**valid, "volume_before": True},
        ):
            with self.subTest(invalid=invalid):
                self.assertFalse(broker_outcome_is_confirmed("close_position", "completed", invalid))

    def test_partial_close_requires_exact_volume_reconciliation(self):
        valid = {
            "status": "confirmed_reduced",
            "volume_before": 500,
            "requested_close_volume": 200,
            "volume_after": 300,
        }
        self.assertTrue(broker_outcome_is_confirmed("close_position", "completed", valid))
        self.assertFalse(broker_outcome_is_confirmed(
            "close_position", "completed", {**valid, "volume_after": 250}
        ))

    def test_close_all_requires_every_position_to_have_confirmed_close_evidence(self):
        position_result = {
            "status": "confirmed_closed",
            "volume_before": 500,
            "requested_close_volume": 500,
            "volume_after": None,
        }
        valid = {
            "status": "confirmed_closed",
            "attempted_count": 1,
            "confirmed_closed_count": 1,
            "positions": [position_result],
        }
        self.assertTrue(broker_outcome_is_confirmed("close_all_positions", "completed", valid))
        self.assertFalse(broker_outcome_is_confirmed(
            "close_all_positions", "completed",
            {**valid, "positions": [{**position_result, "volume_after": 10}]}
        ))
        self.assertFalse(broker_outcome_is_confirmed(
            "close_all_positions", "completed", {**valid, "attempted_count": 2}
        ))

    def test_empty_close_all_requires_explicit_empty_result(self):
        valid = {
            "status": "no_open_positions",
            "attempted_count": 0,
            "confirmed_closed_count": 0,
            "positions": [],
        }
        self.assertTrue(broker_outcome_is_confirmed("close_all_positions", "completed", valid))
        self.assertFalse(broker_outcome_is_confirmed(
            "close_all_positions", "completed", {**valid, "positions": [{}]}
        ))
        self.assertFalse(broker_outcome_is_confirmed(
            "close_all_positions", "completed", {**valid, "attempted_count": False}
        ))
        self.assertFalse(broker_outcome_is_confirmed(
            "close_all_positions", "completed", {**valid, "confirmed_closed_count": False}
        ))

    def test_protection_confirmation_requires_matching_broker_snapshot(self):
        valid = {
            "status": "confirmed_protected",
            "requested_stop_loss": 1.234,
            "requested_take_profit": None,
            "protection_before": {"stop_loss": None, "take_profit": 1.25},
            "protection_after": {"stop_loss": 1.234, "take_profit": 1.25},
        }
        self.assertTrue(broker_outcome_is_confirmed("protect_position", "completed", valid))
        self.assertFalse(broker_outcome_is_confirmed(
            "protect_position", "completed",
            {**valid, "protection_after": {"stop_loss": 1.234, "take_profit": None}}
        ))

    def test_unfinished_or_failed_commands_are_never_confirmed(self):
        result = {
            "status": "confirmed_closed",
            "volume_before": 500,
            "requested_close_volume": 500,
            "volume_after": None,
        }
        self.assertFalse(broker_outcome_is_confirmed("close_position", "processing", result))
        self.assertFalse(broker_outcome_is_confirmed("close_position", "failed", result))


if __name__ == "__main__":
    unittest.main()
