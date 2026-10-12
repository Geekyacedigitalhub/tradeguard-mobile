import unittest

from app.ctrader_execution_guard import entry_block_reason


class CTraderExecutionGuardTests(unittest.TestCase):
    def test_demo_entry_is_blocked_when_sizing_is_unverified(self):
        reason = entry_block_reason("demo", sizing_verified=False)
        self.assertIsNotNone(reason)
        self.assertIn("risk sizing", reason)

    def test_live_entry_is_blocked_even_if_sizing_flag_is_true(self):
        reason = entry_block_reason("live", sizing_verified=True)
        self.assertIsNotNone(reason)
        self.assertIn("Live accounts", reason)

    def test_demo_entry_requires_explicit_verified_sizing(self):
        self.assertIsNone(entry_block_reason("demo", sizing_verified=True))

    def test_unknown_environment_fails_closed(self):
        self.assertIsNotNone(entry_block_reason("unknown", sizing_verified=True))


if __name__ == "__main__":
    unittest.main()
