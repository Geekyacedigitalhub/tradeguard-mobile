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
