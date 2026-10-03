import os
import socket
from contextlib import contextmanager
from urllib.parse import urlparse

try:
    import psycopg
except ImportError:
    psycopg = None

DATABASE_URL = os.getenv("DATABASE_URL")


def _ipv4_hostaddr(database_url):
    parsed = urlparse(database_url)
    host = parsed.hostname
    port = parsed.port or 5432
    if not host:
        return None
    try:
        addresses = socket.getaddrinfo(
            host,
            port,
            socket.AF_INET,
            socket.SOCK_STREAM,
        )
        return addresses[0][4][0] if addresses else None
    except OSError:
        return None


@contextmanager
def connection():
    if not DATABASE_URL or psycopg is None:
        raise RuntimeError("DATABASE_URL/psycopg is not configured")

    hostaddr = _ipv4_hostaddr(DATABASE_URL)
    connect_kwargs = {"connect_timeout": 10}
    if hostaddr:
        connect_kwargs["hostaddr"] = hostaddr

    with psycopg.connect(DATABASE_URL, **connect_kwargs) as conn:
        yield conn
