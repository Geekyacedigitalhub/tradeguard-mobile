"""Regression tests for selected-account consistency during cTrader snapshots."""
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from .ctrader_oauth_api import _assert_selected_demo_account


class _Connection:
    def __init__(self, row):
        self.row = row

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, query, params):
        return self

    def fetchone(self):
        return self.row


class SelectedSnapshotAccountTests(unittest.TestCase):
    def assert_selection_rejected(self, row):
        with patch("backend.app.ctrader_oauth_api.connection", return_value=_Connection(row)):
            with self.assertRaises(HTTPException) as caught:
                _assert_selected_demo_account("user-1", 123)
        self.assertEqual(caught.exception.status_code, 409)

    def test_accepts_same_selected_demo_account(self):
        with patch(
            "backend.app.ctrader_oauth_api.connection",
            return_value=_Connection((123, " DEMO ")),
        ):
            _assert_selected_demo_account("user-1", 123)

    def test_rejects_changed_account(self):
        self.assert_selection_rejected((456, "demo"))

    def test_rejects_live_environment(self):
        self.assert_selection_rejected((123, "live"))

    def test_rejects_invalid_selected_account_id(self):
        self.assert_selection_rejected(("123.5", "demo"))

    def test_rejects_missing_connection(self):
        self.assert_selection_rejected(None)


if __name__ == "__main__":
    unittest.main()
