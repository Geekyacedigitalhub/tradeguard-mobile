import unittest

from app.ctrader_execution_guard import entry_block_reason


def valid_evidence():
    return {
        "account_id": "123",
        "environment": "demo",
        "symbol_id": "456",
        "contract_size": 100000,
        "account_currency": "USD",
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

    def test_non_finite_unit_loss_fails_closed(self):
        evidence = valid_evidence()
        evidence["loss_per_price_unit_per_traded_unit"] = float("nan")
        reason = entry_block_reason("demo", sizing_verified=True, sizing_evidence=evidence, expected_account_id="123", expected_symbol_id="456")
        self.assertIsNotNone(reason)
        self.assertIn("non-positive or non-finite", reason)

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


if __name__ == "__main__":
    unittest.main()
