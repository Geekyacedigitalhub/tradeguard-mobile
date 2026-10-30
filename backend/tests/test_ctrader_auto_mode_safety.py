import os
import unittest
from unittest.mock import patch

os.environ.setdefault("JWT_SECRET", "unit-test-only-not-a-real-secret")

from fastapi import HTTPException
from app import main


class _Result:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row

    def fetchall(self):
        return [self._row] if self._row is not None else []


class FakeConnection:
    """In-memory stand-in for the DB connection.

    Records every query it receives, applies the bot_state mode UPDATE so a
    subsequent SELECT sees the saved mode, and answers the two SELECTs
    main.py issues with fixed rows.
    """

    def __init__(self, demo_account_id=None, environment="demo", mode="semi_auto"):
        self.demo_account_id = demo_account_id
        self.environment = environment
        self.mode = mode
        self.queries = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        normalized = " ".join(query.split())
        self.queries.append(normalized)
        row = None
        if normalized.startswith("SELECT running,emergency_stopped"):
            row = (True, False, self.mode, 0.5, 2.0, 5, 5.0, "2026-10-30 00:00:00")
        elif "FROM ctrader_connections" in normalized:
            row = (self.demo_account_id, self.environment) if self.demo_account_id else None
        elif normalized.startswith("UPDATE bot_state") and params:
            self.mode = params[0]
        return _Result(row)


class CTraderAutoModeSafetyTests(unittest.TestCase):
    def setUp(self):
        main._bot_state_cache.clear()

    def _run(self, mode, demo_account_id=None, environment="demo"):
        fake = FakeConnection(demo_account_id=demo_account_id, environment=environment)
        with patch("app.main.connection", return_value=fake):
            try:
                result = main.update_mode(main.ModeSettings(mode=mode), {"id": "user-1"})
            except HTTPException as exc:
                result = exc
        return fake, result

    def test_full_auto_requires_a_selected_demo_account(self):
        # No account selected: rejected before anything is written.
        fake, result = self._run("full_auto")
        self.assertIsInstance(result, HTTPException)
        self.assertEqual(result.status_code, 409)
        self.assertIn("Demo cTrader account", result.detail)
        self.assertFalse(any(q.startswith("UPDATE bot_state") for q in fake.queries))

    def test_full_auto_rejects_a_selected_live_account(self):
        fake, result = self._run("full_auto", demo_account_id=24680, environment="live")
        self.assertIsInstance(result, HTTPException)
        self.assertEqual(result.status_code, 409)
        self.assertIn("Live accounts never auto-execute", result.detail)
        self.assertFalse(any(q.startswith("UPDATE bot_state") for q in fake.queries))

    def test_full_auto_is_saved_when_a_demo_account_is_selected(self):
        fake, result = self._run("full_auto", demo_account_id=49093168)
        self.assertNotIsInstance(result, HTTPException)
        self.assertTrue(any(q.startswith("UPDATE bot_state") for q in fake.queries))
        self.assertEqual(result["mode"], "full_auto")
        self.assertTrue(result["demo_account_selected"])

    def test_other_modes_never_require_a_broker_account(self):
        for mode in ("signals_only", "semi_auto"):
            with self.subTest(mode=mode):
                fake, result = self._run(mode)
                self.assertNotIsInstance(result, HTTPException)
                self.assertEqual(result["mode"], mode)

    def test_unknown_mode_is_rejected_before_any_db_access(self):
        fake, result = self._run("autonomous")
        self.assertIsInstance(result, HTTPException)
        self.assertEqual(result.status_code, 400)
        self.assertFalse(fake.queries)


if __name__ == "__main__":
    unittest.main()
