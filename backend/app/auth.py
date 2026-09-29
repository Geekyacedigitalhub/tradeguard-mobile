import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from fastapi import Header, HTTPException
from .db import connection

JWT_SECRET = os.getenv("JWT_SECRET", "tradeguard-dev-secret-change-me")
TOKEN_TTL = 60 * 60 * 24 * 30

def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return f"scrypt$\{_b64(salt)}$\{_b64(digest)}"

def verify_password(password: str, encoded: str) -> bool:
    try:
        _, salt_b64, digest_b64 = encoded.split("$", 2)
        salt = _unb64(salt_b64)
        expected = _unb64(digest_b64)
        actual = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False

def create_token(user_id: str) -> str:
    header = _b64(b'{"alg":"HS256","typ":"JWT"}')
    payload = _b64(json.dumps({"sub": user_id, "exp": int(time.time()) + TOKEN_TTL}, separators=(",", ":")).encode())
    signing = f"{header}.{payload}".encode()
    signature = _b64(hmac.new(JWT_SECRET.encode(), signing, hashlib.sha256).digest())
    return f"{header}.{payload}.{signature}"

def _decode_token(token: str) -> str:
    try:
        header, payload, signature = token.split(".")
        signing = f"{header}.{payload}".encode()
        expected = _b64(hmac.new(JWT_SECRET.encode(), signing, hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            raise ValueError()
        data = json.loads(_unb64(payload))
        if int(data["exp"]) < int(time.time()):
            raise ValueError()
        return str(data["sub"])
    except Exception:
        raise HTTPException(401, "Invalid or expired authentication token")

def current_user(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Authentication required")
    user_id = _decode_token(authorization.split(" ", 1)[1].strip())
    with connection() as conn:
        row = conn.execute("SELECT id, email, display_name FROM users WHERE id = %s", (user_id,)).fetchone()
    if not row:
        raise HTTPException(401, "User not found")
    return {"id": str(row[0]), "email": row[1], "display_name": row[2]}
