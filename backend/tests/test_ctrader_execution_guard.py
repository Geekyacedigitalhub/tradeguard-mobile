import unittest
import time

from app.ctrader_execution_guard import entry_block_reason, command_block_reason, close_binding_block_reason, bot_entry_block_reason


def valid_evidence():
    return {
        "account_id": "123",
        "environment": "demo",
        "symbol_id": "456",
        "contract_size": 100000,
        "instrument_type": "FX",
        "contract_model": "linear_fx_base_units",
        "base_asset_id": 1,
        "quote_asset_id": 2,
        "deposit_asset_id": 3,
        "stop_loss_side_validated": True,
        "account_currency": "USD",
        "conversion_verified": True,
        "conversion_source_asset_id": 2,
        "conversion_target_asset_id": 3,
        "conversion_path_symbol_ids": [789],
        "conversion_quote_timestamps_ms": [int(time.time() * 1000)],
        "loss_per_price_unit_per_traded_unit": 1.0,
        "stop_distance": 0.01,
        "risk_amount": 5.0,
        "broker_volume": 500,
        "min_volume": 100,
        "max_volume": 100000,
        "step_volume": 100,
    }


class CTraderExecutionGuardTests(unittest.TestCase):
    def test_demo_entry_is_blocked_when_sizing_is_unverified(self):
        reason = entry_block_reason("demo", sizing_verified=False)
        self.assertIsNotNone(reason)
        self.assertIn("risk sizing", reason)

    def test_live_entry_is_blocked_even_with_complete_evidence(self):
        reason = entry_block_reason("live", sizing_verified=True, sizing_evidence=valid_evidence())
        self.assertIsNotNone(reason)
        self.assertIn("Live accounts", reason)

    def test_demo_entry_requires_complete_evidence(self):
        self.assertIsNone(entry_block_reason("demo", sizing_verified=True, sizing_evidence=valid_evidence(), expected_account_id="123", expected_symbol_id="456"))

    def test_incomplete_evidence_fails_closed(self):
        evidence = valid_evidence()
        del evidence["account_currency"]
        reason = entry_block_reason("demo", sizing_verified=True, sizing_evidence=evidence, expected_account_id="123", expected_symbol_id="456")
        self.assertIsNotNone(reason)
        self.assertIn("incomplete", reason)

    def test_unverified_conversion_fails_closed(self):
        evidence = valid_evidence()
        evidence["conversion_verified"] = False
        reason = entry_block_reason(
            "demo", sizing_verified=True, sizing_evidence=evidence,
            expected_account_id="123", expected_symbol_id="456",
        )
        self.assertIn("conversion is not verified", reason)

    def test_stale_or_future_conversion_quotes_fail_closed(self):
        now_ms = int(time.time() * 1000)
        for timestamp in (now_ms - 6000, now_ms + 1000):
            with self.subTest(timestamp=timestamp):
                evidence = valid_evidence()
                evidence["conversion_quote_timestamps_ms"] = [timestamp]
                reason = entry_block_reason(
                    "demo", sizing_verified=True, sizing_evidence=evidence,
                    expected_account_id="123", expected_symbol_id="456",
                )
                self.assertIn("fresh", reason)

    def test_cross_asset_conversion_requires_quoted_path(self):
        evidence = valid_evidence()
        evidence["conversion_path_symbol_ids"] = []
        evidence["conversion_quote_timestamps_ms"] = []
        reason = entry_block_reason(
            "demo", sizing_verified=True, sizing_evidence=evidence,
            expected_account_id="123", expected_symbol_id="456",
        )
        self.assertIn("no quoted broker path", reason)

    def test_same_asset_conversion_requires_empty_path(self):
        evidence = valid_evidence()
        evidence["conversion_target_asset_id"] = evidence["conversion_source_asset_id"]
        evidence["deposit_asset_id"] = evidence["conversion_source_asset_id"]
        reason = entry_block_reason(
            "demo", sizing_verified=True, sizing_evidence=evidence,
            expected_account_id="123", expected_symbol_id="456",
        )
        self.assertIn("same-asset conversion", reason)

    def test_conversion_path_rejects_repeated_symbol_ids(self):
        evidence = valid_evidence()
        evidence["conversion_path_symbol_ids"] = [789, 789]
        evidence["conversion_quote_timestamps_ms"] = [int(time.time() * 1000), int(time.time() * 1000)]
        reason = entry_block_reason(
            "demo", sizing_verified=True, sizing_evidence=evidence,
            expected_account_id="123", expected_symbol_id="456",
        )
        self.assertIn("repeats a broker symbol ID", reason)

    def test_conversion_quotes_reject_malformed_timestamps(self):
        for timestamp in (True, False, 0, -1, "123", None):
            with self.subTest(timestamp=timestamp):
                evidence = valid_evidence()
                evidence["conversion_quote_timestamps_ms"] = [timestamp]
                reason = entry_block_reason(
                    "demo", sizing_verified=True, sizing_evidence=evidence,
                    expected_account_id="123", expected_symbol_id="456",
                )
                self.assertIn("conversion quote timestamp is invalid", reason)

    def test_conversion_quote_path_requires_matching_timestamp_count(self):
        evidence = valid_evidence()
        evidence["conversion_path_symbol_ids"] = [789, 790]
        evidence["conversion_quote_timestamps_ms"] = [int(time.time() * 1000)]
        reason = entry_block_reason(
            "demo", sizing_verified=True, sizing_evidence=evidence,
            expected_account_id="123", expected_symbol_id="456",
        )
        self.assertIn("conversion quote evidence is incomplete", reason)

    def test_environment_mismatch_fails_closed(self):
        evidence = valid_evidence()
        evidence["environment"] = "live"
        reason = entry_block_reason("demo", sizing_verified=True, sizing_evidence=evidence, expected_account_id="123", expected_symbol_id="456")
        self.assertIsNotNone(reason)
        self.assertIn("environment", reason)

    def test_volume_step_mismatch_fails_closed(self):
        evidence = valid_evidence()
        evidence["broker_volume"] = 550
        reason = entry_block_reason("demo", sizing_verified=True, sizing_evidence=evidence, expected_account_id="123", expected_symbol_id="456")
        self.assertIsNotNone(reason)
        self.assertIn("volume step", reason)

    def test_risk_overrun_fails_closed(self):
        evidence = valid_evidence()
        evidence["risk_amount"] = 0.01
        reason = entry_block_reason("demo", sizing_verified=True, sizing_evidence=evidence, expected_account_id="123", expected_symbol_id="456")
        self.assertIsNotNone(reason)
        self.assertIn("exceeds", reason)

    def test_risk_sizing_accepts_exact_limit_and_rejects_amount_below_calculated_risk(self):
        evidence = valid_evidence()
        # (500 protocol units / 100) * 0.01 stop distance * 1.0 unit loss = 0.05.
        evidence["risk_amount"] = 0.05
        self.assertIsNone(entry_block_reason(
            "demo", sizing_verified=True, sizing_evidence=evidence,
            expected_account_id="123", expected_symbol_id="456",
        ))
        evidence["risk_amount"] = 0.049
        reason = entry_block_reason(
            "demo", sizing_verified=True, sizing_evidence=evidence,
            expected_account_id="123", expected_symbol_id="456",
        )
        self.assertIsNotNone(reason)
        self.assertIn("calculated risk exceeds", reason)

    def test_non_finite_unit_loss_fails_closed(self):
        evidence = valid_evidence()
        evidence["loss_per_price_unit_per_traded_unit"] = float("nan")
        reason = entry_block_reason("demo", sizing_verified=True, sizing_evidence=evidence, expected_account_id="123", expected_symbol_id="456")
        self.assertIsNotNone(reason)
        self.assertIn("non-positive or non-finite", reason)

    def test_overflowed_risk_calculation_fails_closed(self):
        evidence = valid_evidence()
        evidence["stop_distance"] = 1e308
        evidence["loss_per_price_unit_per_traded_unit"] = 1e308
        reason = entry_block_reason(
            "demo", sizing_verified=True, sizing_evidence=evidence,
            expected_account_id="123", expected_symbol_id="456",
        )
        self.assertIsNotNone(reason)
        self.assertIn("calculated risk exceeds", reason)
 
    def test_invalid_contract_size_fails_closed(self):
        for value in (0, -1, float("nan"), float("inf"), -float("inf")):
            with self.subTest(contract_size=value):
                evidence = valid_evidence()
                evidence["contract_size"] = value
                reason = entry_block_reason(
                    "demo", sizing_verified=True, sizing_evidence=evidence,
                    expected_account_id="123", expected_symbol_id="456",
                )
                self.assertIsNotNone(reason)
                self.assertIn("non-positive or non-finite", reason)

    def test_complete_looking_evidence_does_not_bypass_unverified_sizing_flag(self):
        reason = entry_block_reason(
            "demo", sizing_verified=False, sizing_evidence=valid_evidence(),
            expected_account_id="123", expected_symbol_id="456",
        )
        self.assertIsNotNone(reason)
        self.assertIn("risk sizing", reason)

    def test_numeric_sizing_evidence_rejects_booleans_and_strings(self):
        for field, value in (
            ("contract_size", True),
            ("loss_per_price_unit_per_traded_unit", "1.0"),
            ("stop_distance", False),
            ("risk_amount", "5.0"),
        ):
            with self.subTest(field=field, value=value):
                evidence = valid_evidence()
                evidence[field] = value
                reason = entry_block_reason(
                    "demo",
                    sizing_verified=True,
                    sizing_evidence=evidence,
                    expected_account_id="123",
                    expected_symbol_id="456",
                )
                self.assertIsNotNone(reason)
                self.assertIn("must be numeric values", reason)

    def test_boolean_flag_alone_cannot_enable_entries(self):
        self.assertIsNotNone(entry_block_reason("demo", sizing_verified=True))

    def test_sizing_evidence_requires_independently_selected_identity(self):
        reason = entry_block_reason("demo", sizing_verified=True, sizing_evidence=valid_evidence())
        self.assertIsNotNone(reason)
        self.assertIn("identity", reason)

    def test_account_mismatch_fails_closed(self):
        reason = entry_block_reason("demo", sizing_verified=True, sizing_evidence=valid_evidence(), expected_account_id="999", expected_symbol_id="456")
        self.assertIsNotNone(reason)
        self.assertIn("account does not match", reason)

    def test_symbol_mismatch_fails_closed(self):
        reason = entry_block_reason("demo", sizing_verified=True, sizing_evidence=valid_evidence(), expected_account_id="123", expected_symbol_id="999")
        self.assertIsNotNone(reason)
        self.assertIn("symbol does not match", reason)

    def test_fractional_or_boolean_broker_volume_constraints_fail_closed(self):
        for field, value in (
            ("broker_volume", 500.5),
            ("min_volume", True),
            ("max_volume", "100000"),
            ("step_volume", 100.0),
        ):
            with self.subTest(field=field, value=value):
                evidence = valid_evidence()
                evidence[field] = value
                reason = entry_block_reason(
                    "demo",
                    sizing_verified=True,
                    sizing_evidence=evidence,
                    expected_account_id="123",
                    expected_symbol_id="456",
                )
                self.assertIsNotNone(reason)
                self.assertIn("integer protocol values", reason)

    def test_unknown_environment_fails_closed(self):
        self.assertIsNotNone(entry_block_reason("unknown", sizing_verified=True, sizing_evidence=valid_evidence()))





    def test_close_binding_matches_selected_account_and_environment(self):
        payload = {"account_id": 123, "environment": "live", "manual_close": True}
        self.assertIsNone(close_binding_block_reason("live", 123, payload))

    def test_close_binding_rejects_account_switch(self):
        payload = {"account_id": 123, "environment": "live", "manual_close": True}
        reason = close_binding_block_reason("live", 456, payload)
        self.assertIsNotNone(reason)
        self.assertIn("account changed", reason)

    def test_close_binding_rejects_environment_switch(self):
        payload = {"account_id": 123, "environment": "demo", "manual_close": True}
        reason = close_binding_block_reason("live", 123, payload)
        self.assertIsNotNone(reason)
        self.assertIn("environment changed", reason)

    def test_close_binding_rejects_missing_or_invalid_account_id(self):
        for account_id in (None, True, "123", 0, -1):
            with self.subTest(account_id=account_id):
                reason = close_binding_block_reason("demo", 123, {"account_id": account_id, "environment": "demo"})
                self.assertIsNotNone(reason)

    def test_bot_entry_requires_running_and_no_emergency_stop(self):
        self.assertIsNone(bot_entry_block_reason(True, False))
        self.assertIn("not running", bot_entry_block_reason(False, False))
        self.assertIn("emergency stop", bot_entry_block_reason(True, True))

    def test_unknown_bot_state_fails_closed_for_entries(self):
        self.assertIsNotNone(bot_entry_block_reason(None, False))
        self.assertIsNotNone(bot_entry_block_reason(True, None))
        self.assertIsNotNone(bot_entry_block_reason(None, None))

    def test_live_manual_close_is_allowed(self):
        self.assertIsNone(command_block_reason("live", "close_position", {"manual_close": True}))

    def test_manual_close_remains_allowed_when_bot_is_stopped_or_emergency_locked(self):
        # Bot state gates new entries in the worker; it must not remove the
        # user's independent ability to close an existing broker position.
        for running, emergency_stopped in ((False, False), (False, True), (True, True)):
            with self.subTest(running=running, emergency_stopped=emergency_stopped):
                self.assertIsNotNone(bot_entry_block_reason(running, emergency_stopped))
                self.assertIsNone(command_block_reason(
                    "live", "close_position", {"manual_close": True}
                ))

    def test_live_close_without_manual_flag_is_blocked(self):
        reason = command_block_reason("live", "close_position", {})
        self.assertIsNotNone(reason)
        self.assertIn("manual-close authorization", reason)

    def test_live_automated_entry_is_blocked_even_with_manual_flag(self):
        reason = command_block_reason("live", "open_market", {"manual_close": True})
        self.assertIsNotNone(reason)

    def test_live_automatic_protection_change_is_blocked(self):
        self.assertIsNotNone(command_block_reason("live", "protect_position", {"manual_close": True}))

    def test_unknown_environment_is_blocked(self):
        self.assertIsNotNone(command_block_reason("unknown", "close_position", {"manual_close": True}))

    def test_demo_manual_close_is_allowed(self):
        self.assertIsNone(command_block_reason("demo", "close_position", {"manual_close": True}))

    def test_demo_close_without_manual_intent_is_blocked(self):
        reason = command_block_reason("demo", "close_position", {})
        self.assertIsNotNone(reason)
        self.assertIn("manual-close authorization", reason)

    def test_live_manual_close_all_is_allowed(self):
        self.assertIsNone(command_block_reason("live", "close_all_positions", {"manual_close": True}))

    def test_close_all_requires_explicit_manual_intent(self):
        for environment in ("demo", "live"):
            with self.subTest(environment=environment):
                reason = command_block_reason(environment, "close_all_positions", {})
                self.assertIsNotNone(reason)
                self.assertIn("manual-close authorization", reason)

    def test_close_all_rejects_unknown_command_and_environment(self):
        self.assertIsNotNone(command_block_reason("unknown", "close_all_positions", {"manual_close": True}))
        self.assertIsNotNone(command_block_reason("live", "close_everything", {"manual_close": True}))


    def test_boolean_or_malformed_account_and_symbol_ids_are_rejected(self):
        for field, value in (
            ("account_id", True),
            ("account_id", "0"),
            ("account_id", "12.0"),
            ("symbol_id", False),
            ("symbol_id", 0),
            ("symbol_id", "  "),
        ):
            with self.subTest(field=field, value=value):
                evidence = valid_evidence()
                evidence[field] = value
                reason = entry_block_reason(
                    "demo", sizing_verified=True, sizing_evidence=evidence,
                    expected_account_id="123", expected_symbol_id="456",
                )
                self.assertIsNotNone(reason)
                self.assertIn("positive integer identifiers", reason)

    def test_malformed_independently_selected_ids_are_rejected(self):
        for account_id, symbol_id in ((True, "456"), ("123", 4.56), (0, "456"), ("123", None)):
            with self.subTest(account_id=account_id, symbol_id=symbol_id):
                reason = entry_block_reason(
                    "demo", sizing_verified=True, sizing_evidence=valid_evidence(),
                    expected_account_id=account_id, expected_symbol_id=symbol_id,
                )
                self.assertIsNotNone(reason)
                self.assertIn("positive integer identifiers", reason)

if __name__ == "__main__":
    unittest.main()


class CTraderProtectionBindingTests(unittest.TestCase):
    def test_protection_requires_exact_selected_account_and_environment(self):
        payload = {"account_id": 123, "environment": "demo", "position_id": 456}
        self.assertIsNone(close_binding_block_reason("demo", 123, payload))

    def test_protection_binding_rejects_account_switch(self):
        payload = {"account_id": 123, "environment": "demo", "position_id": 456}
        reason = close_binding_block_reason("demo", 999, payload)
        self.assertIsNotNone(reason)
        self.assertIn("account changed", reason)

    def test_protection_binding_rejects_environment_switch(self):
        payload = {"account_id": 123, "environment": "demo", "position_id": 456}
        reason = close_binding_block_reason("live", 123, payload)
        self.assertIsNotNone(reason)
        self.assertIn("environment changed", reason)

    def test_protection_binding_rejects_missing_or_malformed_environment(self):
        for environment in (None, "", "unknown", 123):
            with self.subTest(environment=environment):
                payload = {"account_id": 123, "environment": environment, "position_id": 456}
                self.assertIsNotNone(close_binding_block_reason("demo", 123, payload))

    def test_protection_binding_rejects_malformed_account_ids(self):
        for queued_id, selected_id in ((True, 123), (0, 123), ("123", 123), (123, True), (123, 0)):
            with self.subTest(queued_id=queued_id, selected_id=selected_id):
                payload = {"account_id": queued_id, "environment": "demo", "position_id": 456}
                self.assertIsNotNone(close_binding_block_reason("demo", selected_id, payload))
