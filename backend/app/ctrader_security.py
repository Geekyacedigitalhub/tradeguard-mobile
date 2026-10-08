import base64
import hashlib
import os
from cryptography.fernet import Fernet

def _fernet():
    secret=os.getenv("JWT_SECRET","")
    if not secret:
        raise RuntimeError("JWT_SECRET is required")
    key=base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)

def encrypt_token(value: str | None):
    return _fernet().encrypt(value.encode()).decode() if value else None

def decrypt_token(value: str | None):
    return _fernet().decrypt(value.encode()).decode() if value else None
