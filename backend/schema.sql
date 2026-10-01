CREATE TABLE IF NOT EXISTS bot_state (id INTEGER PRIMARY KEY CHECK (id = 1), running BOOLEAN NOT NULL DEFAULT FALSE, emergency_stopped BOOLEAN NOT NULL DEFAULT FALSE, mode TEXT NOT NULL DEFAULT 'semi_auto', risk_per_trade NUMERIC(6,3) NOT NULL DEFAULT 0.5, daily_loss_limit NUMERIC(6,3) NOT NULL DEFAULT 2.0, max_open_trades INTEGER NOT NULL DEFAULT 3, max_drawdown NUMERIC(6,3) NOT NULL DEFAULT 5.0, updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
CREATE TABLE IF NOT EXISTS signals (id BIGSERIAL PRIMARY KEY, symbol TEXT NOT NULL, signal TEXT NOT NULL, score NUMERIC(5,2) NOT NULL, reason TEXT NOT NULL, entry NUMERIC, stop_loss NUMERIC, take_profit NUMERIC, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
CREATE TABLE IF NOT EXISTS positions (id BIGSERIAL PRIMARY KEY, broker_position_id TEXT, symbol TEXT NOT NULL, side TEXT NOT NULL, quantity NUMERIC NOT NULL, entry NUMERIC NOT NULL, current_price NUMERIC, stop_loss NUMERIC, take_profit NUMERIC, status TEXT NOT NULL DEFAULT 'open', opened_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), closed_at TIMESTAMPTZ);
CREATE TABLE IF NOT EXISTS audit_events (id BIGSERIAL PRIMARY KEY, event_type TEXT NOT NULL, payload JSONB NOT NULL DEFAULT '{}'::jsonb, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
INSERT INTO bot_state (id) VALUES (1) ON CONFLICT (id) DO NOTHING;


CREATE TABLE IF NOT EXISTS trade_journal (
  id BIGSERIAL PRIMARY KEY,
  user_id TEXT NOT NULL,
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
);
CREATE INDEX IF NOT EXISTS trade_journal_user_created_idx ON trade_journal(user_id,created_at DESC);

CREATE TABLE IF NOT EXISTS strategy_reviews (
  id BIGSERIAL PRIMARY KEY,
  user_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  timeframe TEXT NOT NULL,
  report JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS strategy_reviews_user_created_idx ON strategy_reviews(user_id,created_at DESC);
