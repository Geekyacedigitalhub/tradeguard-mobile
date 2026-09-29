# Backend contract

GET /health
GET /v1/account
GET /v1/markets
GET /v1/positions
GET /v1/signals
GET /v1/bot
POST /v1/bot/start
POST /v1/bot/stop
POST /v1/bot/emergency-stop
POST /v1/positions/close-all

Responsibilities: market ingestion, strategy engine, deterministic risk engine, broker adapter, reconciliation, audit logs.
