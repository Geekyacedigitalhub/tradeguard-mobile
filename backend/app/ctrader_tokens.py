from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import httpx

from .ctrader_security import decrypt_token, encrypt_token
from .ctrader_oauth_validation import validate_token_response
from .db import connection


_ACCESS_TOKEN_REFRESH_MARGIN = timedelta(minutes=5)


def _access_token_is_fresh(expires_at, *, now=None) -> bool:
    """Keep using an access token until it is close to expiry."""
    if expires_at is None:
        return False
    now = now or datetime.now(timezone.utc)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return expires_at > now + _ACCESS_TOKEN_REFRESH_MARGIN


def fresh_access_token(user_id: str) -> str:
    # cTrader rotates refresh tokens. Serialize refresh attempts per user by
    # locking the connection row and re-checking expiry after acquiring it.
    # Concurrent API/worker calls then reuse the newly saved token instead of
    # racing to exchange the same refresh token.
    with connection() as conn:
        row = conn.execute(
            """SELECT access_token,refresh_token,expires_at
                 FROM ctrader_connections
                WHERE user_id=%s
                FOR UPDATE""",
            (user_id,),
        ).fetchone()
        if not row:
            raise RuntimeError("cTrader account is not authorized")
        encrypted_access, encrypted_refresh, expires_at = row
        if not encrypted_access:
            raise RuntimeError("cTrader access token is missing")
        if _access_token_is_fresh(expires_at):
            return decrypt_token(encrypted_access)
        if not encrypted_refresh:
            raise RuntimeError("cTrader refresh token is missing")

        response = httpx.post(
            "https://openapi.ctrader.com/apps/token",
            params={
                "grant_type": "refresh_token",
                "refresh_token": decrypt_token(encrypted_refresh),
                "client_id": os.getenv("CTRADER_CLIENT_ID", "").strip(),
                "client_secret": os.getenv("CTRADER_CLIENT_SECRET", "").strip(),
            },
            timeout=15,
        )
        response.raise_for_status()
        token = response.json()
        if isinstance(token, dict) and token.get("errorCode"):
            raise RuntimeError(token.get("description") or str(token["errorCode"]))
        try:
            access, refresh, expires_in = validate_token_response(token)
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc
        expires = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        conn.execute(
            """UPDATE ctrader_connections
                  SET access_token=%s,refresh_token=%s,expires_at=%s,updated_at=now()
                WHERE user_id=%s""",
            (encrypt_token(access), encrypt_token(refresh), expires, user_id),
        )
        return access
