"""Validation for cTrader OAuth token responses before persistence."""
from __future__ import annotations

from typing import Any


def validate_token_response(token: Any) -> tuple[str, str, int]:
    """Return access token, refresh token, and lifetime after strict validation."""
    if not isinstance(token, dict):
        raise ValueError("cTrader authorization returned an invalid response")

    access_token = token.get("accessToken")
    refresh_token = token.get("refreshToken")
    if (
        not isinstance(access_token, str) or not access_token.strip()
        or not isinstance(refresh_token, str) or not refresh_token.strip()
    ):
        raise ValueError("cTrader authorization returned incomplete tokens")

    expires_in = token.get("expiresIn", 2628000)
    # Reject absurd lifetimes before they are used to calculate database
    # expiry timestamps; a broker response must not create effectively
    # non-expiring credentials or overflow datetime arithmetic.
    if (
        isinstance(expires_in, bool)
        or not isinstance(expires_in, int)
        or expires_in <= 0
        or expires_in > 31_536_000
    ):
        raise ValueError("cTrader authorization returned an invalid token lifetime")

    # OAuth responses are external input. Normalize surrounding whitespace before
    # tokens are stored or used in authorization headers.
    return access_token.strip(), refresh_token.strip(), expires_in
