from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import httpx

from .ctrader_security import decrypt_token, encrypt_token
from .db import connection


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
        if expires_at and expires_at > datetime.now(timezone.utc) + timedelta(hours=24):
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
        if token.get("errorCode"):
            raise RuntimeError(token.get("description") or token["errorCode"])
        expires = datetime.now(timezone.utc) + timedelta(
            seconds=int(token.get("expiresIn", 2628000))
        )
        access = token.get("accessToken")
        refresh = token.get("refreshToken")
        if not access or not refresh:
            raise RuntimeError("cTrader token refresh returned incomplete credentials")

        conn.execute(
            """UPDATE ctrader_connections
                  SET access_token=%s,refresh_token=%s,expires_at=%s,updated_at=now()
                WHERE user_id=%s""",
            (encrypt_token(access), encrypt_token(refresh), expires, user_id),
        )
        return access
