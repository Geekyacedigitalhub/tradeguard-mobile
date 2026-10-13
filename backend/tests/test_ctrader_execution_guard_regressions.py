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
