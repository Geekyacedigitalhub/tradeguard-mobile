import os
import unittest

os.environ.setdefault("JWT_SECRET", "unit-test-only-not-a-real-secret")

from app.ctrader_worker import _preflight_command_block_reason


class CTraderQueuedAccountBindingTests(unittest.TestCase):
    def test_queued_entry_for_different_account_is_rejected(self):
        reason = _preflight_command_block_reason(
            "demo",
            456,
            "open_market",
            {
                "execution_provider": "ctrader",
                "account_id": 123,
                "environment": "demo",
                "risk_amount": 5,
            },
        )
        self.assertIsNotNone(reason)
        self.assertIn("account changed", reason.lower())

    def test_queued_entry_for_different_environment_is_rejected(self):
        reason = _preflight_command_block_reason(
            "demo",
            123,
            "open_market",
            {
                "execution_provider": "ctrader",
                "account_id": 123,
                "environment": "live",
                "risk_amount": 5,
            },
        )
        self.assertIsNotNone(reason)
        self.assertIn("environment changed", reason.lower())


    def test_queued_entry_requires_a_valid_account_binding(self):
        invalid_bindings = [
            ({"environment": "demo", "risk_amount": 5}, "account binding"),
            ({"account_id": 0, "environment": "demo", "risk_amount": 5}, "account binding"),
            ({"account_id": True, "environment": "demo", "risk_amount": 5}, "account binding"),
            ({"account_id": 123, "risk_amount": 5}, "environment changed"),
            ({"account_id": 123, "environment": "", "risk_amount": 5}, "environment changed"),
        ]
        for payload, expected in invalid_bindings:
            with self.subTest(payload=payload):
                reason = _preflight_command_block_reason(
                    "demo", 123, "open_market",
                    {"execution_provider": "ctrader", **payload},
                )
                self.assertIsNotNone(reason)
                self.assertIn(expected, reason.lower())

    def test_live_entry_stays_blocked_even_with_matching_binding(self):
        reason = _preflight_command_block_reason(
            "live",
            123,
            "open_market",
            {
                "execution_provider": "ctrader",
                "account_id": 123,
                "environment": "live",
                "risk_amount": 5,
            },
        )
        self.assertIsNotNone(reason)
        self.assertIn("live ctrader permits manual position closes only", reason.lower())


if __name__ == "__main__":
    unittest.main()
