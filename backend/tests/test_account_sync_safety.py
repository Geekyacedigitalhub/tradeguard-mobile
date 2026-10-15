from datetime import datetime, timezone, timedelta
import unittest
from unittest.mock import patch

from app import account_sync


class _Result:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class _Connection:
    def __init__(self, selected, heartbeat):
        self.selected = selected
        self.heartbeat = heartbeat
        self.calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query, _params):
        self.calls += 1
        if "FROM ctrader_connections" in query:
            return _Result(self.selected)
        if "FROM audit_events" in query:
            return _Result(self.heartbeat)
        raise AssertionError("Unexpected query; legacy account_state must not be used")


class AccountSyncSafetyTests(unittest.TestCase):
    def setUp(self):
        account_sync._ACCOUNT_CACHE.clear()

    def _connection(self, payload, selected=(1234, "demo"), created_at=None):
        stamp = created_at or datetime.now(timezone.utc)
        return _Connection(selected, (payload, stamp))

    def test_missing_verified_risk_metrics_fail_closed(self):
        payload = {
            "connected": True,
            "terminal": "cTrader Cloud",
            "provider": "cTrader",
            "environment": "demo",
            "account": 1234,
        }
        fake = self._connection(payload)
        with patch.object(account_sync, "connection", return_value=fake):
            self.assertIsNone(account_sync.live_account_metrics("user-1"))

    def test_fresh_complete_ctrader_metrics_are_returned(self):
        payload = {
            "connected": True,
            "terminal": "cTrader Cloud",
            "provider": "cTrader",
            "environment": "demo",
            "account": 1234,
            "balance": 1000,
            "equity": 990,
            "today_pl": -10,
            "drawdown": 1,
            "currency": "USD",
        }
        fake = self._connection(payload)
        with patch.object(account_sync, "connection", return_value=fake):
            result = account_sync.live_account_metrics("user-2")
        self.assertEqual(result["balance"], 1000.0)
        self.assertEqual(result["equity"], 990.0)
        self.assertEqual(result["drawdown"], 1.0)

    def test_missing_or_malformed_currency_fails_closed(self):
        base = {
            "connected": True,
            "terminal": "cTrader Cloud",
            "provider": "cTrader",
            "environment": "demo",
            "account": 1234,
            "balance": 1000,
            "equity": 1000,
            "today_pl": 0,
            "drawdown": 0,
        }
        for currency in (None, "", "usd", "US", "USDD", "USD "):
            with self.subTest(currency=currency):
                payload = dict(base)
                if currency is not None:
                    payload["currency"] = currency
                fake = self._connection(payload)
                with patch.object(account_sync, "connection", return_value=fake):
                    self.assertIsNone(account_sync.live_account_metrics(f"currency-{currency!r}"))

    def test_mismatched_selected_account_is_rejected(self):
        payload = {
            "connected": True,
            "terminal": "cTrader Cloud",
            "provider": "cTrader",
            "environment": "demo",
            "account": 9999,
            "balance": 1000,
            "equity": 1000,
            "today_pl": 0,
            "drawdown": 0,
        }
        fake = self._connection(payload, selected=(1234, "demo"))
        with patch.object(account_sync, "connection", return_value=fake):
            self.assertIsNone(account_sync.live_account_metrics("user-3"))


    def test_snapshot_helpers_reject_malformed_identifiers_and_volumes(self):
        from app.ctrader_snapshot_helpers import positive_integer, scale_balance, normalize_trade_side

        self.assertEqual(positive_integer("123"), 123)
        for value in (None, True, 0, -1, 1.5, "1.5", "invalid"):
            with self.subTest(value=value):
                self.assertIsNone(positive_integer(value))
        self.assertEqual(scale_balance(123456, 2), 1234.56)
        self.assertIsNone(scale_balance(float("inf"), 2))
        self.assertEqual(normalize_trade_side(1), "BUY")
        self.assertEqual(normalize_trade_side("invalid"), "UNKNOWN")

    def test_stale_heartbeat_is_rejected(self):
        payload = {
            "connected": True,
            "terminal": "cTrader Cloud",
            "provider": "cTrader",
            "environment": "demo",
            "account": 1234,
            "balance": 1000,
            "equity": 1000,
            "today_pl": 0,
            "drawdown": 0,
        }
        fake = self._connection(payload, created_at=datetime.now(timezone.utc) - timedelta(seconds=60))
        with patch.object(account_sync, "connection", return_value=fake):
            self.assertIsNone(account_sync.live_account_metrics("user-4"))


if __name__ == "__main__":
    unittest.main()
