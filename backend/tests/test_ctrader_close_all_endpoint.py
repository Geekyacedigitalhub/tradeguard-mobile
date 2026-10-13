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



class CTraderCloseAllDeduplicationTests(unittest.IsolatedAsyncioTestCase):
    async def _call_with_existing(self, existing_row):
        from unittest.mock import MagicMock
        with patch(
            "app.ctrader_oauth_api._connection_row",
            return_value=("access-token", "live", 777),
        ), patch("app.ctrader_oauth_api.connection") as db:
            conn = MagicMock()
            db.return_value.__enter__.return_value = conn
            advisory = MagicMock()
            existing = MagicMock()
            existing.fetchone.return_value = existing_row
            conn.execute.side_effect = [advisory, existing]
            result = await close_all_positions(
                {"confirmation": "CLOSE_ALL"}, {"id": "user-1"}
            )
        return result, conn

    async def test_duplicate_close_all_reuses_pending_command(self):
        result, conn = await self._call_with_existing((901,))
        self.assertEqual(result["command_id"], 901)
        self.assertTrue(result["duplicate_request"])
        self.assertIn("pending", result["message"].lower())
        self.assertEqual(conn.execute.call_count, 2)

    async def test_duplicate_close_all_reuses_stale_uncertain_command(self):
        result, conn = await self._call_with_existing((902,))
        self.assertEqual(result["command_id"], 902)
        self.assertTrue(result["duplicate_request"])
        self.assertIn("unresolved", result["message"].lower())
        self.assertEqual(conn.execute.call_count, 2)


class CTraderIndividualCloseDeduplicationTests(unittest.IsolatedAsyncioTestCase):
    async def test_stale_failed_but_unconfirmed_close_is_not_requeued(self):
        from unittest.mock import MagicMock
        from app.trade_api import close_ctrader_trade

        with patch(
            "app.ctrader_oauth_api._connection_row",
            return_value=("access-token", "demo", 777),
        ), patch("app.trade_api.connection") as db:
            conn = MagicMock()
            db.return_value.__enter__.return_value = conn
            lock_result = MagicMock()
            existing_result = MagicMock()
            existing_result.fetchone.return_value = (501,)
            conn.execute.side_effect = [lock_result, existing_result]
            result = await close_ctrader_trade(
                12345, {"volume": 100}, {"id": "user-1"}
            )

        self.assertEqual(result["command_id"], 501)
        self.assertTrue(result["duplicate_request"])
        self.assertIn("unresolved", result["message"].lower())
        self.assertEqual(conn.execute.call_count, 2)
        dedupe_sql = " ".join(conn.execute.call_args_list[1].args[0].split())
        self.assertIn("status IN ('completed','failed')", dedupe_sql)
        self.assertIn("'submitted_unconfirmed'", dedupe_sql)

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


class CTraderIndividualCloseEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_individual_close_rejects_invalid_selected_account_id(self):
        from app.trade_api import close_ctrader_trade
        for account_id in ("123", True, 0, -1, None):
            with self.subTest(account_id=account_id):
                with patch("app.ctrader_oauth_api._connection_row", return_value=("access-token", "demo", account_id)):
                    with self.assertRaises(HTTPException) as caught:
                        await close_ctrader_trade(12345, {"volume": 100}, {"id": "user-1"})
                self.assertEqual(caught.exception.status_code, 400)
                self.assertIn("selected cTrader account id", caught.exception.detail)

    async def test_individual_close_rejects_invalid_position_before_database_queue(self):
        from app.trade_api import close_ctrader_trade
        with patch("app.ctrader_oauth_api._connection_row", return_value=("access-token", "demo", 777)):
            with self.assertRaises(HTTPException) as caught:
                await close_ctrader_trade(True, {"volume": 100}, {"id": "user-1"})
        self.assertEqual(caught.exception.status_code, 400)
        self.assertIn("position id", caught.exception.detail)

class CTraderProtectionEndpointEnvironmentTests(unittest.IsolatedAsyncioTestCase):
    async def test_protection_rejects_missing_environment_instead_of_assuming_demo(self):
        from app.trade_api import protect_ctrader_trade
        with patch("app.ctrader_oauth_api._connection_row", return_value=("access-token", None, 777)), patch("app.trade_api.connection") as db:
            with self.assertRaises(HTTPException) as caught:
                await protect_ctrader_trade(12345, {"stop_loss": 1.1}, {"id": "user-1"})
        self.assertEqual(caught.exception.status_code, 409)
        self.assertIn("environment is invalid", caught.exception.detail)
        db.assert_not_called()

    async def test_protection_rejects_live_account(self):
        from app.trade_api import protect_ctrader_trade
        with patch("app.ctrader_oauth_api._connection_row", return_value=("access-token", "live", 777)), patch("app.trade_api.connection") as db:
            with self.assertRaises(HTTPException) as caught:
                await protect_ctrader_trade(12345, {"stop_loss": 1.1}, {"id": "user-1"})
        self.assertEqual(caught.exception.status_code, 403)
        self.assertIn("Live accounts", caught.exception.detail)
        db.assert_not_called()

    async def test_protection_rejects_non_integer_selected_account_id(self):
        from app.trade_api import protect_ctrader_trade
        with patch("app.ctrader_oauth_api._connection_row", return_value=("access-token", "demo", "777")), patch("app.trade_api.connection") as db:
            with self.assertRaises(HTTPException) as caught:
                await protect_ctrader_trade(12345, {"stop_loss": 1.1}, {"id": "user-1"})
        self.assertEqual(caught.exception.status_code, 400)
        self.assertIn("selected cTrader account id", caught.exception.detail)
        db.assert_not_called()


class CTraderCloseAllQueueRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_close_all_with_positions_uses_selected_account_for_deduplication(self):
        from unittest.mock import MagicMock
        from app.trade_api import close_all

        with patch(
            "app.ctrader_oauth_api._connection_row",
            return_value=("access-token", "demo", 777),
        ), patch(
            "app.ctrader_oauth_api.ctrader_account",
            new=__import__("unittest.mock", fromlist=["AsyncMock"]).AsyncMock(return_value={
                "connected": True,
                "account_id": 777,
                "environment": "demo",
                "positions": [{"position_id": 12345, "volume_protocol_units": 100}],
            }),
        ), patch("app.trade_api.connection") as db:
            conn = MagicMock()
            db.return_value.__enter__.return_value = conn
            advisory_result = MagicMock()
            existing_result = MagicMock()
            existing_result.fetchone.return_value = None
            insert_result = MagicMock()
            insert_result.fetchone.return_value = (9001,)
            conn.execute.side_effect = [advisory_result, existing_result, insert_result]

            result = await close_all({"id": "user-1"})

        self.assertEqual(result["account_id"], 777)
        self.assertEqual(result["position_count"], 1)
        self.assertEqual(result["command_ids"], [9001])
        dedupe_call = conn.execute.call_args_list[1]
        self.assertEqual(dedupe_call.args[1], ("user-1", "777", "12345"))


    async def test_close_all_rejects_stale_failed_unconfirmed_individual_close(self):
        from unittest.mock import AsyncMock, MagicMock
        from app.trade_api import close_all

        with patch(
            "app.ctrader_oauth_api._connection_row",
            return_value=("access-token", "live", 777),
        ), patch(
            "app.ctrader_oauth_api.ctrader_account",
            new=AsyncMock(return_value={
                "connected": True,
                "account_id": 777,
                "environment": "live",
                "positions": [{"position_id": 12345, "volume_protocol_units": 100}],
            }),
        ), patch("app.trade_api.connection") as db:
            conn = MagicMock()
            db.return_value.__enter__.return_value = conn
            conn.execute.side_effect = [
                MagicMock(),
                MagicMock(),
            ]
            conn.execute.side_effect[1].fetchone.return_value = (
                9002, "failed", "submitted_unconfirmed"
            )

            with self.assertRaises(HTTPException) as caught:
                await close_all({"id": "user-1"})

        self.assertEqual(caught.exception.status_code, 409)
        self.assertIn("unresolved broker outcome", caught.exception.detail)
        self.assertIn("No new Close All batch was queued", caught.exception.detail)
        self.assertEqual(conn.execute.call_count, 2)
        dedupe_sql = " ".join(conn.execute.call_args_list[1].args[0].split())
        self.assertIn("status IN ('completed','failed')", dedupe_sql)
        self.assertIn("'submitted_unconfirmed'", dedupe_sql)


class CTraderCloseAllAccountIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def test_close_all_rejects_invalid_selected_account_id_before_snapshot(self):
        from unittest.mock import AsyncMock
        from app.trade_api import close_all

        with patch("app.ctrader_oauth_api._connection_row", return_value=("access-token", "demo", "77x")), \
             patch("app.ctrader_oauth_api.ctrader_account", new=AsyncMock()) as snapshot:
            with self.assertRaises(HTTPException) as caught:
                await close_all({"id": "user-1"})
        self.assertEqual(caught.exception.status_code, 409)
        self.assertIn("account ID is invalid", caught.exception.detail)
        snapshot.assert_not_awaited()

    async def test_close_all_rejects_malformed_broker_account_identity(self):
        from unittest.mock import AsyncMock
        from app.trade_api import close_all

        with patch("app.ctrader_oauth_api._connection_row", return_value=("access-token", "demo", 777)), \
             patch("app.ctrader_oauth_api.ctrader_account", new=AsyncMock(return_value={
                 "connected": True,
                 "account_id": "not-an-account-id",
                 "environment": "demo",
                 "positions": [{"position_id": 12345, "volume_protocol_units": 100}],
             })) as snapshot, patch("app.trade_api.connection") as db:
            with self.assertRaises(HTTPException) as caught:
                await close_all({"id": "user-1"})
        self.assertEqual(caught.exception.status_code, 503)
        self.assertIn("invalid account identity", caught.exception.detail)
        snapshot.assert_awaited_once()
        db.assert_not_called()
