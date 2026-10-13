import asyncio
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("JWT_SECRET", "unit-test-only-not-a-real-secret")

from app import ctrader_worker


class EmptyResult:
    def fetchall(self):
        return []


class ClaimConnection:
    def __init__(self):
        self.queries = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        self.queries.append(" ".join(query.split()))
        return EmptyResult()


class CTraderWorkerClaimTests(unittest.TestCase):
    def test_each_claim_resets_claim_timestamp(self):
        fake_connection = ClaimConnection()
        with patch.object(ctrader_worker, "connection", return_value=fake_connection), patch.object(
            ctrader_worker, "_fail_stale_ctrader_commands"
        ):
            asyncio.run(ctrader_worker.process_ctrader_commands())

        claim_queries = [
            query for query in fake_connection.queries
            if "UPDATE bridge_commands bc" in query and "SET status='processing'" in query
        ]
        self.assertEqual(len(claim_queries), 1)
        self.assertIn("claimed_at=now()", claim_queries[0])
        self.assertNotIn("COALESCE(bc.claimed_at", claim_queries[0])


    def test_finish_update_only_targets_processing_command(self):
        fake_connection = ClaimConnection()
        with patch.object(ctrader_worker, "connection", return_value=fake_connection):
            ctrader_worker._finish(42, {"status": "failed"}, "failed")

        self.assertEqual(len(fake_connection.queries), 1)
        self.assertIn("WHERE id=%s AND status=", fake_connection.queries[0])
        self.assertIn("processing", fake_connection.queries[0])


if __name__ == "__main__":
    unittest.main()
