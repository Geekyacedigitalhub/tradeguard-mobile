from __future__ import annotations

import math
import os
from datetime import datetime, timedelta, timezone

import httpx

from .ctrader_security import decrypt_token, encrypt_token
from .db import connection


def _token_expiry_seconds(value: object) -> int:
    """Validate the lifetime returned by cTrader before persisting credentials."""
    if isinstance(value, bool):
        raise RuntimeError("cTrader returned an invalid token expiry")
    try:
        seconds = int(value)
        numeric = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise RuntimeError("cTrader returned an invalid token expiry") from exc
    if not math.isfinite(numeric) or numeric != seconds or seconds <= 0:
        raise RuntimeError("cTrader returned an invalid token expiry")
    return seconds


def fresh_access_token(user_id: str) -> str:
    with connection() as conn:
        row = conn.execute(
            "SELECT access_token,refresh_token,expires_at FROM ctrader_connections WHERE user_id=%s",
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

    client_id = os.getenv("CTRADER_CLIENT_ID", "").strip()
    client_secret = os.getenv("CTRADER_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise RuntimeError("cTrader Open API credentials are not configured")

    response = httpx.post(
        "https://openapi.ctrader.com/apps/token",
        params={
            "grant_type": "refresh_token",
            "refresh_token": decrypt_token(encrypted_refresh),
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=15,
    )
    response.raise_for_status()
    try:
        token = response.json()
    except ValueError as exc:
        raise RuntimeError("cTrader returned an unreadable token refresh response") from exc
    if not isinstance(token, dict):
        raise RuntimeError("cTrader returned an invalid token response")
    if token.get("errorCode"):
        raise RuntimeError(str(token.get("description") or token["errorCode"]))

    access = token.get("accessToken")
    refresh = token.get("refreshToken")
    if not isinstance(access, str) or not access.strip() or not isinstance(refresh, str) or not refresh.strip():
        raise RuntimeError("cTrader token refresh returned incomplete credentials")
    lifetime = _token_expiry_seconds(token.get("expiresIn", 2628000))
    expires = datetime.now(timezone.utc) + timedelta(seconds=lifetime)

    with connection() as conn:
        conn.execute(
            """UPDATE ctrader_connections
                  SET access_token=%s,refresh_token=%s,expires_at=%s,updated_at=now()
                WHERE user_id=%s""",
            (encrypt_token(access), encrypt_token(refresh), expires, user_id),
        )
    return access
