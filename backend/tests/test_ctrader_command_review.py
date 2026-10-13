import unittest

from app.trade_api import _requires_broker_review


class CommandReviewTests(unittest.TestCase):
    def test_unconfirmed_protection_requires_broker_review(self):
        self.assertTrue(
            _requires_broker_review(
                "protect_position", "failed", "submitted_unconfirmed", False
            )
        )

    def test_confirmed_protection_does_not_require_review(self):
        self.assertFalse(
            _requires_broker_review(
                "protect_position", "completed", "confirmed_protected", True
            )
        )

    def test_unconfirmed_close_still_requires_review(self):
        self.assertTrue(
            _requires_broker_review(
                "close_position", "failed", "submitted_unconfirmed", False
            )
        )

    def test_non_execution_commands_do_not_require_broker_review(self):
        self.assertFalse(
            _requires_broker_review(
                "refresh_account", "failed", "submitted_unconfirmed", False
            )
        )


if __name__ == "__main__":
    unittest.main()
