import unittest
from unittest.mock import patch

from app.ctrader_execution_guard import (
    bot_entry_block_reason,
    close_binding_block_reason,
    command_block_reason,
    entry_block_reason,
)


class CTraderExecutionGuardTests(unittest.TestCase):
    def test_live_automated_entry_is_blocked_even_if_sizing_claimed_verified(self):
        reason = entry_block_reason("live", sizing_verified=True, sizing_evidence={})
        self.assertIn("disabled", reason.lower())

    def test_live_entry_stays_blocked_even_with_complete_looking_sizing_payload(self):
        evidence = {
            "account_id": 123, "environment": "demo", "symbol_id": 45,
            "contract_size": 100000, "instrument_type": "FX",
            "contract_model": "linear_fx_base_units", "base_asset_id": 1,
            "quote_asset_id": 2, "deposit_asset_id": 2,
            "stop_loss_side_validated": True, "account_currency": "USD",
            "conversion_verified": True, "conversion_source_asset_id": 2,
            "conversion_target_asset_id": 2, "conversion_path_symbol_ids": [],
            "conversion_quote_timestamps_ms": [], "loss_per_price_unit_per_traded_unit": 1.0,
            "stop_distance": 0.01, "risk_amount": 10.0, "broker_volume": 100,
            "min_volume": 100, "max_volume": 100000, "step_volume": 100,
        }
        reason = entry_block_reason(
            "live", sizing_verified=True, sizing_evidence=evidence,
            expected_account_id=123, expected_symbol_id=45,
        )
        self.assertIn("Live accounts", reason)

    def test_unknown_bot_state_fails_closed(self):
        self.assertIsNotNone(bot_entry_block_reason(True, None))
        self.assertIsNotNone(bot_entry_block_reason(None, False))

    def test_emergency_stop_blocks_entries_but_not_manual_close_policy(self):
        self.assertIsNotNone(bot_entry_block_reason(True, True))
        payload = {
            "manual_close": True,
            "account_id": 123,
            "environment": "live",
        }
        self.assertIsNone(command_block_reason("live", "close_position", payload))
        self.assertIsNone(close_binding_block_reason("live", 123, payload))

    def test_manual_close_cannot_be_replayed_against_changed_account(self):
        payload = {
            "manual_close": True,
            "account_id": 123,
            "environment": "demo",
        }
        reason = close_binding_block_reason("demo", 456, payload)
        self.assertIn("account changed", reason.lower())

    def test_manual_close_requires_explicit_intent(self):
        self.assertIsNotNone(command_block_reason(
            "demo", "close_position", {"account_id": 123, "environment": "demo"}
        ))


if __name__ == "__main__":
    unittest.main()
