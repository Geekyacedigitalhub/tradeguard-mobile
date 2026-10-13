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


if __name__ == "__main__":
    unittest.main()
