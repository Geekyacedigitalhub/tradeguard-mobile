import unittest
from types import SimpleNamespace

from app.ctrader_service import CTraderManager, _Session


class CTraderSessionSafetyTests(unittest.TestCase):
    def setUp(self):
        self.manager = CTraderManager()
        self.session = _Session(client=SimpleNamespace(), environment="demo", ready=True)
        self.session.accounts[12345] = "user-1"
        self.manager._sessions["demo"] = self.session

    def test_account_ready_requires_valid_positive_integer(self):
        self.assertTrue(self.manager.account_ready("demo", 12345))
        for value in (None, 0, -1, True, 1.5, "bad"):
            with self.subTest(value=repr(value)):
                self.assertFalse(self.manager.account_ready("demo", value))

    def test_account_ready_is_false_when_session_not_ready(self):
        self.session.ready = False
        self.assertFalse(self.manager.account_ready("demo", 12345))

    def test_disconnect_clears_stale_account_authorizations(self):
        self.manager._disconnected("demo", "test disconnect")
        self.assertFalse(self.session.ready)
        self.assertEqual(self.session.accounts, {})
        self.assertFalse(self.manager.account_ready("demo", 12345))

    def test_remember_account_does_not_authorize_when_session_not_ready(self):
        self.session.ready = False
        self.manager.remember_account("demo", 67890, "user-2")
        self.assertNotIn(67890, self.session.accounts)


if __name__ == "__main__":
    unittest.main()
