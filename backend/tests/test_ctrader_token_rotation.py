import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("JWT_SECRET", "unit-test-only-not-a-real-secret")

from app.ctrader_service import CTraderManager


def _manager_with_session():
    manager = CTraderManager()
    session = SimpleNamespace(
        client=SimpleNamespace(send=None),
        environment="demo",
        ready=True,
        waiters={},
        logout_before_auth=False,
        authorized_accounts=set(),
        authorized_tokens={},
        spot_subscriptions={},
        spot_subscription_refs={},
        spot_waiters={},
        latest_spots={},
        symbol_digits={},
    )
    manager._sessions["demo"] = session
    return manager, session


class TokenRotationTests(unittest.IsolatedAsyncioTestCase):
    """The broker binds an account authorization to the access token used.

    Tokens rotate (fresh_access_token refreshes before expiry). A cached
    authorization made with an old token must not suppress re-authorization
    with the new token: otherwise broker data calls keep failing against a
    dead token until the transport happens to drop (the 2026-10-29
    'ACCOUNT SNAPSHOT STALE' window on-device).
    """

    async def test_same_token_reuses_cached_authorization(self):
        manager, session = _manager_with_session()
        session.authorized_accounts.add(42)
        session.authorized_tokens[42] = "tok-1"
        send = AsyncMock()
        with patch.object(manager, "_send", new=send), \
             patch.object(manager, "_session", return_value=session):
            result = await manager.authorize_account(42, "tok-1", "demo")
        self.assertTrue(result["cached"])
        send.assert_not_awaited()

    async def test_rotated_token_triggers_reauthorization(self):
        manager, session = _manager_with_session()
        session.authorized_accounts.add(42)
        session.authorized_tokens[42] = "tok-1"  # stale: authorized with old token
        authorized = SimpleNamespace(ctidTraderAccountId=42)
        with patch.object(manager, "_send", new=AsyncMock(return_value=authorized)), \
             patch.object(manager, "_session", return_value=session):
            await manager.authorize_account(42, "tok-2", "demo")
        self.assertIn(42, session.authorized_accounts)
        self.assertEqual(session.authorized_tokens[42], "tok-2")

    async def test_failed_reauthorization_clears_stale_cache(self):
        manager, session = _manager_with_session()
        session.authorized_accounts.add(42)
        session.authorized_tokens[42] = "tok-1"
        with patch.object(manager, "_send", new=AsyncMock(side_effect=RuntimeError("broker rejected"))), \
             patch.object(manager, "_session", return_value=session):
            with self.assertRaises(RuntimeError):
                await manager.authorize_account(42, "tok-2", "demo")
        self.assertNotIn(42, session.authorized_accounts)
        self.assertNotIn(42, session.authorized_tokens)
