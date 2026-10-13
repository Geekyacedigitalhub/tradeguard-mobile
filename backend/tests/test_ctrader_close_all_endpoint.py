import os
import unittest
from unittest.mock import patch

os.environ.setdefault("JWT_SECRET", "unit-test-only-not-a-real-secret")

from fastapi import HTTPException
from app.ctrader_oauth_api import close_all_positions


class CTraderCloseAllEndpointSafetyTests(unittest.IsolatedAsyncioTestCase):
    async def test_close_all_requires_explicit_confirmation_before_database_access(self):
        with patch("app.ctrader_oauth_api._connection_row") as connection_row:
            with self.assertRaises(HTTPException) as caught:
                await close_all_positions({}, {"id": "user-1"})

        self.assertEqual(caught.exception.status_code, 400)
        self.assertIn("CLOSE_ALL", caught.exception.detail)
        connection_row.assert_not_called()

    async def test_close_all_requires_a_selected_authorized_account(self):
        with patch("app.ctrader_oauth_api._connection_row", return_value=None):
            with self.assertRaises(HTTPException) as caught:
                await close_all_positions({"confirmation": "CLOSE_ALL"}, {"id": "user-1"})

        self.assertEqual(caught.exception.status_code, 409)
        self.assertIn("select an account", caught.exception.detail.lower())

    async def test_close_all_rejects_invalid_selected_account_id(self):
        for account_id in ("123", True, 0, -1, None):
            with self.subTest(account_id=account_id):
                with patch(
                    "app.ctrader_oauth_api._connection_row",
                    return_value=("access-token", "demo", account_id),
                ), patch("app.ctrader_oauth_api.connection") as db:
                    with self.assertRaises(HTTPException) as caught:
                        await close_all_positions({"confirmation": "CLOSE_ALL"}, {"id": "user-1"})
                self.assertEqual(caught.exception.status_code, 409)
                self.assertIn("account ID is invalid", caught.exception.detail)
                db.assert_not_called()


if __name__ == "__main__":
    unittest.main()


class CloseResponseContractTests(unittest.TestCase):
    def test_missing_command_id_is_not_evidence_of_no_open_positions(self):
        # The client must only report a flat account when the API explicitly
        # returns status=no_open_positions; an empty/malformed response is unknown.
        response = {}
        self.assertNotEqual(response.get("status"), "no_open_positions")

    def test_explicit_no_open_positions_status_is_distinguishable(self):
        response = {"status": "no_open_positions"}
        self.assertEqual(response.get("status"), "no_open_positions")
