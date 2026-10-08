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


def ensure_schema():
    """Create the TradeGuard application schema on a fresh database."""
    statements = [
        """CREATE TABLE IF NOT EXISTS users (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            display_name TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS account_state (
            user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            balance NUMERIC NOT NULL DEFAULT 10000,
            equity NUMERIC NOT NULL DEFAULT 10000,
            today_pl NUMERIC NOT NULL DEFAULT 0,
            drawdown NUMERIC NOT NULL DEFAULT 0,
            currency TEXT NOT NULL DEFAULT 'USD',
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS bot_state (
            user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            running BOOLEAN NOT NULL DEFAULT FALSE,
            emergency_stopped BOOLEAN NOT NULL DEFAULT FALSE,
            mode TEXT NOT NULL DEFAULT 'semi_auto',
            risk_per_trade NUMERIC(6,3) NOT NULL DEFAULT 0.5,
            daily_loss_limit NUMERIC(6,3) NOT NULL DEFAULT 2.0,
            max_open_trades INTEGER NOT NULL DEFAULT 3,
            max_drawdown NUMERIC(6,3) NOT NULL DEFAULT 5.0,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS signals (
            id BIGSERIAL PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            symbol TEXT NOT NULL,
            action TEXT NOT NULL,
            score NUMERIC(5,2) NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            entry NUMERIC,
            stop_loss NUMERIC,
            take_profit NUMERIC,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS positions (
            id BIGSERIAL PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            broker_position_id TEXT,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            quantity NUMERIC NOT NULL,
            entry NUMERIC NOT NULL,
            current_price NUMERIC,
            stop_loss NUMERIC,
            take_profit NUMERIC,
            status TEXT NOT NULL DEFAULT 'open',
            opened_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            closed_at TIMESTAMPTZ,
            close_reason TEXT,
            realized_pnl NUMERIC NOT NULL DEFAULT 0
        )""",
        """CREATE TABLE IF NOT EXISTS audit_events (
            id BIGSERIAL PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            event_type TEXT NOT NULL,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS bridge_pairings (
            bridge_id TEXT PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS bridge_pairing_codes (
            bridge_id TEXT PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            code_hash TEXT NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            used_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS bridge_credentials (
            bridge_id TEXT PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash TEXT NOT NULL UNIQUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            revoked_at TIMESTAMPTZ
        )""",
        """CREATE TABLE IF NOT EXISTS bridge_market_data (
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            candles JSONB NOT NULL DEFAULT '[]'::jsonb,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (user_id, symbol, timeframe)
        )""",
        """CREATE TABLE IF NOT EXISTS bridge_commands (
            id BIGSERIAL PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            command_type TEXT NOT NULL,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            claimed_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            result JSONB NOT NULL DEFAULT '{}'::jsonb
        )""",
        """CREATE TABLE IF NOT EXISTS trade_journal (
            id BIGSERIAL PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            symbol TEXT NOT NULL,
            side TEXT,
            setup TEXT,
            timeframe TEXT,
            entry NUMERIC,
            stop_loss NUMERIC,
            take_profit NUMERIC,
            outcome TEXT,
            pnl NUMERIC,
            r_multiple NUMERIC,
            notes TEXT NOT NULL DEFAULT '',
            tags JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            closed_at TIMESTAMPTZ
        )""",
        """CREATE TABLE IF NOT EXISTS strategy_reviews (
            id BIGSERIAL PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            report JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS cloud_market_candles (
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            candle_time BIGINT NOT NULL,
            open NUMERIC NOT NULL,
            high NUMERIC NOT NULL,
            low NUMERIC NOT NULL,
            close NUMERIC NOT NULL,
            volume NUMERIC NOT NULL DEFAULT 0,
            source TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (symbol, timeframe, candle_time)
        )""",
        """CREATE INDEX IF NOT EXISTS signals_user_created_idx ON signals(user_id, created_at DESC)""",
        """CREATE INDEX IF NOT EXISTS signals_recent_lookup_idx ON signals(user_id, symbol, action, created_at DESC)""",
        """CREATE INDEX IF NOT EXISTS positions_user_status_idx ON positions(user_id, status, opened_at DESC)""",
        """CREATE INDEX IF NOT EXISTS positions_status_idx ON positions(status, opened_at DESC)""",
        """CREATE INDEX IF NOT EXISTS positions_user_closed_idx ON positions(user_id, status, closed_at DESC)""",
        """CREATE INDEX IF NOT EXISTS audit_events_user_created_idx ON audit_events(user_id, created_at DESC)""",
        """CREATE INDEX IF NOT EXISTS audit_events_type_lookup_idx ON audit_events(user_id, event_type, created_at DESC)""",
        """CREATE INDEX IF NOT EXISTS bridge_commands_user_status_idx ON bridge_commands(user_id, status, id)""",
        """CREATE INDEX IF NOT EXISTS trade_journal_user_created_idx ON trade_journal(user_id, created_at DESC)""",
        """CREATE INDEX IF NOT EXISTS strategy_reviews_user_created_idx ON strategy_reviews(user_id, created_at DESC)""",
        """CREATE INDEX IF NOT EXISTS strategy_reviews_gate_lookup_idx ON strategy_reviews(user_id, symbol, timeframe, created_at DESC)""",
        """CREATE INDEX IF NOT EXISTS cloud_market_candles_lookup_idx ON cloud_market_candles(symbol, timeframe, candle_time DESC)""",
    ]
    # Lightweight migrations for databases created by earlier TradeGuard builds.
    # CREATE TABLE IF NOT EXISTS does not add columns to an existing table.
    migration_statements = [
        "ALTER TABLE trade_journal ADD COLUMN IF NOT EXISTS broker_ticket TEXT",
        "ALTER TABLE trade_journal ADD COLUMN IF NOT EXISTS exit_price NUMERIC",
        "ALTER TABLE trade_journal ADD COLUMN IF NOT EXISTS context JSONB NOT NULL DEFAULT '{}'::jsonb",
        "CREATE INDEX IF NOT EXISTS trade_journal_ticket_idx ON trade_journal(user_id,broker_ticket)",
        "CREATE UNIQUE INDEX IF NOT EXISTS trade_journal_ticket_unique_idx ON trade_journal(user_id,broker_ticket) WHERE broker_ticket IS NOT NULL",
        "ALTER TABLE bridge_pairing_codes ADD COLUMN IF NOT EXISTS user_id UUID",
        "ALTER TABLE bridge_pairing_codes ADD COLUMN IF NOT EXISTS code_hash TEXT",
        "ALTER TABLE bridge_pairing_codes ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ",
        "ALTER TABLE bridge_pairing_codes ADD COLUMN IF NOT EXISTS used_at TIMESTAMPTZ",
        "ALTER TABLE bridge_pairing_codes ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW()",
        "ALTER TABLE bridge_credentials ADD COLUMN IF NOT EXISTS user_id UUID",
        "ALTER TABLE bridge_credentials ADD COLUMN IF NOT EXISTS token_hash TEXT",
        "ALTER TABLE bridge_credentials ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW()",
        "ALTER TABLE bridge_credentials ADD COLUMN IF NOT EXISTS revoked_at TIMESTAMPTZ",
        """CREATE TABLE IF NOT EXISTS bridge_bootstrap_tokens (
            bridge_id TEXT PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash TEXT NOT NULL UNIQUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            revoked_at TIMESTAMPTZ
        )""",
    ]
    with connection() as conn:
        for statement in statements:
            conn.execute(statement)
        for statement in migration_statements:
            conn.execute(statement)
