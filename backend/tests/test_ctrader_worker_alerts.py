import os
import unittest
from unittest.mock import patch

os.environ.setdefault("JWT_SECRET", "unit-test-only-not-a-real-secret")

from app.ctrader_worker import _publish_position_alert


class CTraderPositionAlertTests(unittest.TestCase):
    @patch("app.ctrader_worker.send_push")
    @patch("app.ctrader_worker.notification_event")
    def test_confirmed_close_is_logged_and_pushed(self, event, push):
        _publish_position_alert(
            "user-1", "close_position",
            {"position_id": 77, "environment": "live"},
            {"status": "confirmed_closed", "position_id": 77, "environment": "live"},
        )
        self.assertEqual(event.call_args.args[1], "notification_trade_closed")
        self.assertEqual(event.call_args.args[2]["status"], "confirmed_closed")
        self.assertIn("confirmed", push.call_args.args[1].lower())
        self.assertEqual(push.call_args.args[3]["environment"], "live")

    @patch("app.ctrader_worker.send_push")
    @patch("app.ctrader_worker.notification_event")
    def test_partial_close_warns_to_check_remaining_volume(self, event, push):
        _publish_position_alert(
            "user-1", "close_position",
            {"position_id": 78, "environment": "demo"},
            {"status": "confirmed_reduced", "position_id": 78, "environment": "demo"},
        )
        self.assertEqual(event.call_args.args[1], "notification_trade_partially_closed")
        self.assertIn("remaining volume", push.call_args.args[2])

    @patch("app.ctrader_worker.send_push")
    @patch("app.ctrader_worker.notification_event")
    def test_unconfirmed_close_does_not_claim_position_is_closed(self, event, push):
        _publish_position_alert(
            "user-1", "close_position",
            {"position_id": 79, "environment": "live"},
            {"status": "submitted_unconfirmed", "position_id": 79, "environment": "live"},
        )
        self.assertEqual(event.call_args.args[1], "notification_trade_close_unconfirmed")
        self.assertIn("before retrying", push.call_args.args[2])


    @patch("app.ctrader_worker.send_push")
    @patch("app.ctrader_worker.notification_event")
    def test_unexpected_position_change_is_not_alerted_as_closed(self, event, push):
        _publish_position_alert(
            "user-1", "close_position",
            {"position_id": 82, "environment": "live"},
            {"status": "changed_unexpectedly", "position_id": 82, "environment": "live"},
        )
        self.assertEqual(event.call_args.args[1], "notification_trade_close_unconfirmed")
        self.assertNotEqual(event.call_args.args[1], "notification_trade_closed")
        self.assertIn("Check the broker account before retrying", push.call_args.args[2])

    @patch("app.ctrader_worker.send_push")
    @patch("app.ctrader_worker.notification_event")
    def test_protection_failure_advises_broker_check(self, event, push):
        _publish_position_alert(
            "user-1", "protect_position",
            {"position_id": 80, "environment": "demo"},
            {"error": "broker timeout"},
            failed=True,
        )
        self.assertEqual(event.call_args.args[1], "notification_protection_failed")
        self.assertIn("at the broker", push.call_args.args[2])

    @patch("app.ctrader_worker.send_push")
    @patch("app.ctrader_worker.notification_event", side_effect=RuntimeError("history unavailable"))
    def test_push_is_attempted_even_if_alert_history_write_fails(self, event, push):
        _publish_position_alert(
            "user-1", "close_position",
            {"position_id": 81, "environment": "live"},
            {"status": "confirmed_closed", "position_id": 81, "environment": "live"},
        )
        event.assert_called_once()
        push.assert_called_once()

    def test_non_position_command_does_not_send_position_alert(self):
        with patch("app.ctrader_worker.notification_event") as event, patch("app.ctrader_worker.send_push") as push:
            _publish_position_alert("user-1", "open_market", {}, {"status": "failed"}, failed=True)
        event.assert_not_called()
        push.assert_not_called()



    @patch("app.ctrader_worker.send_push")
    @patch("app.ctrader_worker.notification_event")
    def test_close_all_fully_confirmed_is_reported_as_confirmed(self, event, push):
        result = {
            "status": "confirmed_closed",
            "environment": "live",
            "attempted_count": 2,
            "confirmed_closed_count": 2,
            "positions": [
                {"position_id": 91, "status": "confirmed_closed"},
                {"position_id": 92, "status": "confirmed_closed"},
            ],
        }
        _publish_position_alert(
            "user-1", "close_all_positions",
            {"environment": "live", "manual_close": True}, result,
        )
        self.assertEqual(event.call_args.args[1], "notification_close_all_confirmed")
        self.assertEqual(event.call_args.args[2]["result"]["confirmed_closed_count"], 2)
        self.assertIn("2 positions closed", push.call_args.args[2])

    @patch("app.ctrader_worker.send_push")
    @patch("app.ctrader_worker.notification_event")
    def test_partial_close_all_warns_to_check_broker(self, event, push):
        result = {
            "status": "partially_closed",
            "environment": "live",
            "attempted_count": 3,
            "confirmed_closed_count": 1,
            "positions": [
                {"position_id": 93, "status": "confirmed_closed"},
                {"position_id": 94, "status": "unconfirmed"},
                {"position_id": 95, "status": "failed"},
            ],
        }
        _publish_position_alert(
            "user-1", "close_all_positions",
            {"environment": "live", "manual_close": True}, result,
        )
        self.assertEqual(event.call_args.args[1], "notification_close_all_unconfirmed")
        self.assertIn("1/3 positions reported closed", push.call_args.args[2])
        self.assertIn("Check the broker account now", push.call_args.args[2])

    @patch("app.ctrader_worker.send_push")
    @patch("app.ctrader_worker.notification_event")
    def test_close_all_inconsistent_confirmed_counts_are_downgraded(self, event, push):
        _publish_position_alert(
            "user-1", "close_all_positions",
            {"environment": "live", "manual_close": True},
            {
                "status": "confirmed_closed",
                "environment": "live",
                "attempted_count": 2,
                "confirmed_closed_count": 2,
                "positions": [
                    {"position_id": 96, "status": "confirmed_closed"},
                    {"position_id": 97, "status": "unconfirmed"},
                ],
            },
        )
        self.assertEqual(event.call_args.args[1], "notification_close_all_unconfirmed")
        self.assertIn("incomplete or inconsistent", push.call_args.args[2])

    @patch("app.ctrader_worker.send_push")
    @patch("app.ctrader_worker.notification_event")
    def test_close_all_missing_position_evidence_is_not_confirmed(self, event, push):
        _publish_position_alert(
            "user-1", "close_all_positions",
            {"environment": "live", "manual_close": True},
            {
                "status": "confirmed_closed",
                "environment": "live",
                "attempted_count": 1,
                "confirmed_closed_count": 1,
            },
        )
        self.assertEqual(event.call_args.args[1], "notification_close_all_unconfirmed")
        self.assertIn("incomplete or inconsistent", push.call_args.args[2])

    @patch("app.ctrader_worker.send_push")
    @patch("app.ctrader_worker.notification_event")
    def test_close_all_with_no_open_positions_is_confirmed(self, event, push):
        _publish_position_alert(
            "user-1", "close_all_positions",
            {"environment": "demo", "manual_close": True},
            {
                "status": "no_open_positions",
                "environment": "demo",
                "attempted_count": 0,
                "confirmed_closed_count": 0,
                "positions": [],
            },
        )
        self.assertEqual(event.call_args.args[1], "notification_close_all_confirmed")
        self.assertIn("nothing needed closing", push.call_args.args[2])

    @patch("app.ctrader_worker.send_push")
    @patch("app.ctrader_worker.notification_event")
    def test_preflight_close_all_failure_has_no_fake_counts(self, event, push):
        _publish_position_alert("user-1", "close_all_positions", {"environment": "live"}, {"status": "failed"}, failed=True)
        self.assertEqual(event.call_args.args[1], "notification_close_all_unconfirmed")

    @patch("app.ctrader_worker.send_push")
    @patch("app.ctrader_worker.notification_event")
    def test_close_all_preflight_reason_is_preserved_in_alert(self, event, push):
        reason = "Close All was not submitted because broker volume data was invalid."
        _publish_position_alert(
            "user-1", "close_all_positions", {"environment": "live"},
            {"status": "unconfirmed", "attempted_count": 0,
             "confirmed_closed_count": 0, "positions": [], "reason": reason},
        )
        self.assertEqual(event.call_args.args[1], "notification_close_all_unconfirmed")
        self.assertIn(reason, push.call_args.args[2])
        self.assertNotIn("0/0", push.call_args.args[2])


    @patch("app.ctrader_worker.send_push")
    @patch("app.ctrader_worker.notification_event")
    def test_stale_close_all_alert_explains_broker_outcome_is_unknown(self, event, push):
        _publish_position_alert(
            "user-1", "close_all_positions",
            {"environment": "live", "manual_close": True},
            {
                "provider": "ctrader",
                "status": "submitted_unconfirmed",
                "error": "Worker stopped responding; broker outcome is unknown.",
            },
        )
        self.assertEqual(event.call_args.args[1], "notification_close_all_unconfirmed")
        self.assertIn("outcome is unknown", push.call_args.args[2])
        self.assertIn("before retrying", push.call_args.args[2])
        self.assertNotIn("invalid result", push.call_args.args[2].lower())

    @patch("app.ctrader_worker.send_push")
    @patch("app.ctrader_worker.notification_event")
    def test_unconfirmed_protection_is_not_reported_as_protected(self, event, push):
        _publish_position_alert(
            "user-1", "protect_position",
            {"position_id": 83, "environment": "live"},
            {"status": "submitted_unconfirmed", "position_id": 83, "environment": "live"},
        )
        self.assertEqual(event.call_args.args[1], "notification_protection_unconfirmed")
        self.assertNotEqual(event.call_args.args[1], "notification_position_protected")
        self.assertIn("Check the broker account", push.call_args.args[2])
        self.assertEqual(push.call_args.args[3]["status"], "submitted_unconfirmed")



class CTraderManualCloseVolumeTests(unittest.TestCase):
    def test_manual_close_uses_fresh_broker_volume_not_stale_mobile_volume(self):
        from app.ctrader_worker import _close_volume_for_snapshot
        self.assertEqual(_close_volume_for_snapshot(100, 150, True), 150)

    def test_manual_close_does_not_exceed_fresh_broker_volume_when_snapshot_was_larger(self):
        from app.ctrader_worker import _close_volume_for_snapshot
        self.assertEqual(_close_volume_for_snapshot(200, 150, True), 150)

    def test_non_manual_close_keeps_explicit_requested_volume(self):
        from app.ctrader_worker import _close_volume_for_snapshot
        self.assertEqual(_close_volume_for_snapshot(50, 150, False), 50)


class CTraderWorkerAccountAndAggregateTests(unittest.TestCase):
    def test_selected_account_id_must_be_positive_integer_without_coercion(self):
        from app.ctrader_worker import _validated_selected_account
        for account_id in ("123", True, 0, -1, None):
            with self.subTest(account_id=account_id):
                with self.assertRaises(RuntimeError):
                    _validated_selected_account((account_id, "demo"))

    def test_selected_account_environment_must_be_explicit_demo_or_live(self):
        from app.ctrader_worker import _validated_selected_account
        for environment in (None, "", "paper"):
            with self.subTest(environment=environment):
                with self.assertRaises(RuntimeError):
                    _validated_selected_account((123, environment))

    def test_valid_selected_account_is_returned_without_conversion(self):
        from app.ctrader_worker import _validated_selected_account
        self.assertEqual(_validated_selected_account((123, " LIVE ")), (123, "live"))

    def test_preflight_rejects_account_switch_before_broker_authorization(self):
        from app.ctrader_worker import _preflight_command_block_reason
        reason = _preflight_command_block_reason(
            "live", 456, "close_position",
            {"account_id": 123, "environment": "live", "manual_close": True},
        )
        self.assertIsNotNone(reason)
        self.assertIn("account changed", reason)

    def test_preflight_rejects_environment_switch_before_broker_authorization(self):
        from app.ctrader_worker import _preflight_command_block_reason
        reason = _preflight_command_block_reason(
            "live", 123, "close_all_positions",
            {"account_id": 123, "environment": "demo", "manual_close": True},
        )
        self.assertIsNotNone(reason)
        self.assertIn("environment changed", reason)

    def test_stale_ctrader_commands_are_marked_uncertain_not_requeued(self):
        from unittest.mock import patch
        from app.ctrader_worker import _fail_stale_ctrader_commands

        class FakeResult:
            def fetchall(self):
                return [
                    (1, "user-1", "close_position", {"position_id": 42}),
                    (2, "user-1", "protect_position", {"position_id": 43}),
                ]

        class FakeConnection:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def execute(self, query, params):
                self.query = query
                self.params = params
                self.__class__.last_query = query
                self.__class__.last_params = params
                return FakeResult()

        with patch("app.ctrader_worker.connection", return_value=FakeConnection()), \
             patch("app.ctrader_worker._publish_position_alert") as publish_alert:
            self.assertEqual(_fail_stale_ctrader_commands(), 2)

        self.assertEqual(publish_alert.call_count, 2)
        self.assertEqual(publish_alert.call_args_list[0].args[1], "close_position")
        self.assertEqual(publish_alert.call_args_list[1].args[1], "protect_position")
        self.assertFalse(publish_alert.call_args_list[0].kwargs["failed"])
        self.assertFalse(publish_alert.call_args_list[1].kwargs["failed"])
        self.assertIn("SET status='failed'", FakeConnection.last_query)
        self.assertIn("claimed_at IS NULL OR claimed_at < now() - interval '15 minutes'", FakeConnection.last_query)
        self.assertNotIn("SET status='pending'", FakeConnection.last_query)
        self.assertIn("submitted_unconfirmed", FakeConnection.last_params[0])

    def test_selected_account_binding_is_rechecked_before_broker_action(self):
        from unittest.mock import patch
        from app.ctrader_worker import _assert_selected_account_binding

        class FakeConnection:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def execute(self, *args):
                class Result:
                    def fetchone(self):
                        return (456, "live")
                return Result()

        with patch("app.ctrader_worker.connection", return_value=FakeConnection()):
            with self.assertRaisesRegex(RuntimeError, "account changed"):
                _assert_selected_account_binding("user-1", 123, "live")

    def test_selected_environment_binding_is_rechecked_before_broker_action(self):
        from unittest.mock import patch
        from app.ctrader_worker import _assert_selected_account_binding

        class FakeConnection:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def execute(self, *args):
                class Result:
                    def fetchone(self):
                        return (123, "demo")
                return Result()

        with patch("app.ctrader_worker.connection", return_value=FakeConnection()):
            with self.assertRaisesRegex(RuntimeError, "environment changed"):
                _assert_selected_account_binding("user-1", 123, "live")

    def test_selected_account_binding_allows_unchanged_account(self):
        from unittest.mock import patch
        from app.ctrader_worker import _assert_selected_account_binding

        class FakeConnection:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def execute(self, *args):
                class Result:
                    def fetchone(self):
                        return (123, "live")
                return Result()

        with patch("app.ctrader_worker.connection", return_value=FakeConnection()):
            self.assertIsNone(_assert_selected_account_binding("user-1", 123, "live"))

    def test_preflight_allows_bound_manual_live_close(self):
        from app.ctrader_worker import _preflight_command_block_reason
        self.assertIsNone(_preflight_command_block_reason(
            "live", 123, "close_position",
            {"account_id": 123, "environment": "live", "manual_close": True},
        ))

    def test_preflight_keeps_live_protection_amendments_blocked(self):
        from app.ctrader_worker import _preflight_command_block_reason
        reason = _preflight_command_block_reason(
            "live", 123, "protect_position",
            {"account_id": 123, "environment": "live"},
        )
        self.assertIsNotNone(reason)
        self.assertIn("Live cTrader permits manual position closes only", reason)

    def test_close_all_aggregate_never_counts_partial_close_as_fully_closed(self):
        from app.ctrader_worker import _close_all_result
        result = _close_all_result("live", 123, [
            {"position_id": 11, "status": "confirmed_closed"},
            {"position_id": 12, "status": "confirmed_reduced"},
            {"position_id": 13, "status": "unconfirmed"},
        ])
        self.assertEqual(result["status"], "partially_closed")
        self.assertEqual(result["attempted_count"], 3)
        self.assertEqual(result["confirmed_closed_count"], 1)

    def test_close_all_aggregate_requires_every_position_to_be_confirmed(self):
        from app.ctrader_worker import _close_all_result
        result = _close_all_result("live", 123, [
            {"position_id": 21, "status": "unconfirmed"},
            {"position_id": 22, "status": "failed"},
            {"position_id": 23, "status": "changed_unexpectedly"},
        ])
        self.assertEqual(result["status"], "unconfirmed")
        self.assertEqual(result["attempted_count"], 3)
        self.assertEqual(result["confirmed_closed_count"], 0)

    def test_close_all_aggregate_confirms_only_all_confirmed_closes(self):
        from app.ctrader_worker import _close_all_result
        result = _close_all_result("live", 123, [
            {"position_id": 31, "status": "confirmed_closed"},
            {"position_id": 32, "status": "confirmed_closed"},
        ])
        self.assertEqual(result["status"], "confirmed_closed")
        self.assertEqual(result["attempted_count"], 2)
        self.assertEqual(result["confirmed_closed_count"], 2)

    def test_empty_close_all_snapshot_is_explicitly_no_open_positions(self):
        from app.ctrader_worker import _close_all_result
        result = _close_all_result("demo", 123, [])
        self.assertEqual(result["status"], "no_open_positions")
        self.assertEqual(result["attempted_count"], 0)
        self.assertEqual(result["confirmed_closed_count"], 0)

class CTraderCommandClaimTests(unittest.TestCase):
    def test_stale_or_failed_command_cannot_start_another_broker_action(self):
        from unittest.mock import patch
        from app.ctrader_worker import _assert_command_processing

        class FakeResult:
            def fetchone(self):
                return ("failed",)

        class FakeConnection:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def execute(self, query, params):
                self.query = query
                self.params = params
                return FakeResult()

        with patch("app.ctrader_worker.connection", return_value=FakeConnection()):
            with self.assertRaisesRegex(RuntimeError, "no longer owns an active execution claim"):
                _assert_command_processing(123)

    def test_active_processing_command_keeps_its_execution_claim(self):
        from unittest.mock import patch
        from app.ctrader_worker import _assert_command_processing

        class FakeResult:
            def fetchone(self):
                return ("processing",)

        class FakeConnection:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def execute(self, query, params):
                return FakeResult()

        with patch("app.ctrader_worker.connection", return_value=FakeConnection()):
            self.assertIsNone(_assert_command_processing(124))


if __name__ == "__main__":
    unittest.main()
