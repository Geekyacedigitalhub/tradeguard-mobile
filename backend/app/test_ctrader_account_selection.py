"""Regression tests for fail-closed cTrader demo-account selection."""
import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from .ctrader_oauth_api import select_account


class SelectAccountSafetyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.context = MagicMock()
        self.conn = self.context.__enter__.return_value
        self.db_patch = patch(
            "backend.app.ctrader_oauth_api.connection",
            return_value=self.context,
        )
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        self.token_patch = patch(
            "backend.app.ctrader_oauth_api.fresh_access_token",
            return_value="fresh-token",
        )
        self.token_patch.start()
        self.addCleanup(self.token_patch.stop)
        self.accounts_patch = patch(
            "backend.app.ctrader_oauth_api.manager.list_accounts",
        )
        self.list_accounts = self.accounts_patch.start()
        self.addCleanup(self.accounts_patch.stop)
        self.authorize_patch = patch(
            "backend.app.ctrader_oauth_api.manager.authorize_account",
        )
        self.authorize = self.authorize_patch.start()
        self.addCleanup(self.authorize_patch.stop)
        self.remember_patch = patch(
            "backend.app.ctrader_oauth_api.manager.remember_account",
        )
        self.remember = self.remember_patch.start()
        self.addCleanup(self.remember_patch.stop)
        self.conn.execute.return_value.fetchone.return_value = ("encrypted-token", "demo")

    async def test_rejects_account_without_explicit_demo_flag(self):
        self.list_accounts.return_value = [{"account_id": 123}]
        with self.assertRaises(HTTPException) as caught:
            await select_account({"account_id": 123}, user={"id": "user-1"})
        self.assertEqual(caught.exception.status_code, 403)
        self.authorize.assert_not_awaited()
        self.remember.assert_not_called()

    async def test_rejects_live_account(self):
        self.list_accounts.return_value = [{"account_id": 123, "is_live": True}]
        with self.assertRaises(HTTPException) as caught:
            await select_account({"account_id": 123}, user={"id": "user-1"})
        self.assertEqual(caught.exception.status_code, 403)
        self.authorize.assert_not_awaited()

    async def test_rejects_malformed_account_list(self):
        self.list_accounts.return_value = None
        with self.assertRaises(HTTPException) as caught:
            await select_account({"account_id": 123}, user={"id": "user-1"})
        self.assertEqual(caught.exception.status_code, 503)
        self.authorize.assert_not_awaited()

    async def test_accepts_explicit_demo_account(self):
        self.list_accounts.return_value = [{"account_id": 123, "is_live": False}]
        self.authorize.return_value = None
        result = await select_account({"account_id": 123}, user={"id": "user-1"})
        self.assertEqual(result["account_id"], 123)
        self.assertEqual(result["environment"], "demo")
        self.authorize.assert_awaited_once_with(123, "fresh-token", "demo")
        self.remember.assert_called_once_with("demo", 123, "user-1")


if __name__ == "__main__":
    unittest.main()
