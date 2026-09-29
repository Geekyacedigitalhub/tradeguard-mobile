import os
from contextlib import contextmanager
try:
    import psycopg
except ImportError:
    psycopg = None
DATABASE_URL = os.getenv("DATABASE_URL")
@contextmanager
def connection():
    if not DATABASE_URL or psycopg is None:
        raise RuntimeError("DATABASE_URL/psycopg is not configured")
    with psycopg.connect(DATABASE_URL) as conn:
        yield conn
