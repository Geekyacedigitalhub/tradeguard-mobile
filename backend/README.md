# Backend contract

FastAPI service entry point: `backend/app/main.py` (`app.main:app`). Interactive
documentation is available at `/docs` on a running instance.

## Environment

Copy `.env.example` and fill in every required value. The process refuses to
start without `JWT_SECRET`, and every authenticated request needs
`DATABASE_URL`. See `.env.example` for the cTrader and optional operational
secrets.

`CORS_ALLOW_ORIGINS` (default `*`) controls browser access. Native React Native
clients ignore CORS, but Expo web, local previews and API tooling need it.
Sessions use bearer tokens rather than cookies, so a wildcard origin cannot
leak a session; set an explicit origin list for a production web front end.

## Public endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Process heartbeat only; not proof of broker connectivity |
| POST | `/v1/auth/register` | Create an account and session token |
| POST | `/v1/auth/login` | Exchange credentials for a session token |
| GET | `/v1/auth/me` | Current user |
| GET | `/v1/account` | Verified cTrader balance/equity, drawdown and risk profile |
| GET | `/v1/markets` | Cached multi-timeframe scan of TradeGuard's market universe |
| GET | `/v1/markets/{symbol}/candles` | Candle history for the mobile chart (`5m`, `15m`, `1h`) |
| GET | `/v1/signals` | BUY/SELL rows from the current market scan |
| POST | `/v1/risk/check` | Server-side risk evaluation of a candidate signal |
| GET/POST | `/v1/journal` | Trade journal list and entry creation |
| GET | `/v1/journal/stats` | Journal performance totals |
| GET | `/v1/journal/learning`, `/v1/journal/optimizer` | Learning and optimizer health |
| GET | `/v1/knowledge` | Strategy knowledge base |
| GET | `/v1/notifications/events` | Alert history |
| GET | `/v1/notifications/status` | Push registration status |
| POST | `/v1/notifications/test` | Send a test Expo push |
| POST | `/v1/notifications/token` | Register an Expo push token |
| DELETE | `/v1/notifications/token` | Detach this device on sign-out (revokes delivery) |

## Bot and risk

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/v1/bot` | Engine state and risk envelope |
| POST | `/v1/bot/start` / `/v1/bot/stop` | Start or stop monitoring |
| PUT | `/v1/bot/mode` | `signals_only` or `semi_auto`; `full_auto` returns 409 |
| PUT | `/v1/bot/risk` | Update the stored risk envelope |
| GET/PUT | `/v1/bot/ai-approval` | AI auto-approval settings |
| POST | `/v1/bot/emergency-stop` | Latch: stop the bot and block new entries |
| POST | `/v1/bot/reset-emergency` | Clear the latch without restarting the bot |

## cTrader

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/v1/ctrader/oauth/start` | Build the cTrader authorization URL |
| GET | `/v1/ctrader/oauth/callback` | OAuth callback; stores encrypted tokens, returns a page linking back to the app (`?format=json` for tooling) |
| GET | `/v1/ctrader/oauth/status` | Authorization and selected-account state |
| GET | `/v1/ctrader/connection` | Connection detail and execution permissions |
| GET | `/v1/ctrader/accounts` | Accounts available to the authorization |
| POST | `/v1/ctrader/accounts/select` | Bind one account and environment |
| GET | `/v1/ctrader/account` | Broker account snapshot with positions and P/L |
| GET | `/v1/ctrader/symbols` | Broker symbol catalogue |
| GET | `/v1/ctrader/preflight` | Read-only pretrade sizing/readiness check |
| POST | `/v1/ctrader/positions/close-all` | Manual, broker-confirmed close-all request |
| WS | `/v1/ctrader/market-stream?token=…` | Authenticated cTrader spot tick stream |

Trade endpoints under `/v1/trades` operate on TradeGuard's internal journal
records and the cTrader command queue. `/v1/trades/{position_id}/close` is
intentionally disabled (HTTP 410) because an internal record is not a broker
position. Use the cTrader position routes for broker actions.

## Background work

- `ctrader_command_worker` claims queued cTrader commands and verifies every
  broker outcome.
- `ctrader_equity_snapshot_worker` records equity for drawdown tracking.
- `market_alert_cycle` scans markets for alerts.
- `auto_trade_cycle` evaluates automated entries, but the execution guard keeps
  every automated entry blocked until broker-verified, symbol-specific account
  currency risk sizing exists.

## Safety invariants

- Automated order execution is disabled for both Demo and Live until broker
  sizing is verified. Do not remove that guard to "enable trading".
- Brand-new results are never invented: missing broker balance, equity,
  positions, P/L or currency are reported as unavailable.
- A queued close command is not a confirmed close; only a broker-confirmed
  response is reported as closed.

## Verifying a deployment

From the repository root:

```bash
npm run api:check -- --base-url https://your-api-host
npm run api:check -- --base-url https://your-api-host --email you@example.com --password 'your-password'
```

The smoke test checks `/health`, the CORS preflight, anonymous rejection,
sign-in and every authenticated endpoint the mobile app calls.

## Tests

```bash
cd backend
python -m pip install -e .
python -m unittest discover -s tests -v
```

`tests/test_api_surface.py` covers the connection contract: `/health` without
authentication, 401 on protected routes, CORS headers for browser clients and
the registered market-stream WebSocket route.
