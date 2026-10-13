import os
import unittest
from unittest.mock import patch

os.environ.setdefault("JWT_SECRET", "unit-test-only-not-a-real-secret")

from fastapi import HTTPException
from app import main


class CTraderAutoModeSafetyTests(unittest.TestCase):
    def test_full_auto_mode_is_rejected_before_any_setting_is_saved(self):
        with patch("app.main.connection") as connection:
            with self.assertRaises(HTTPException) as caught:
                main.update_mode(main.ModeSettings(mode="full_auto"), {"id": "user-1"})

        self.assertEqual(caught.exception.status_code, 409)
        self.assertIn("paused", caught.exception.detail.lower())
        self.assertIn("No orders were queued", caught.exception.detail)
        connection.assert_not_called()

    def test_unknown_mode_is_rejected(self):
        with patch("app.main.connection") as connection:
            with self.assertRaises(HTTPException) as caught:
                main.update_mode(main.ModeSettings(mode="autonomous"), {"id": "user-1"})

        self.assertEqual(caught.exception.status_code, 400)
        connection.assert_not_called()


if __name__ == "__main__":
    unittest.main()
