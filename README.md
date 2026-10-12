# TradeGuard Mobile

TradeGuard is a React Native + Expo trading control center backed by FastAPI and PostgreSQL/Neon.

## Broker and execution architecture

- Broker integration: cTrader Open API through cloud OAuth and token refresh.
- Account visibility: Demo and Live cTrader accounts can be authorized and selected for read-only account inspection.
- Automated order execution: hard-gated to cTrader Demo while the live execution rollout is not approved.
- Market research: cloud candle sources with strict freshness checks before any execution-facing signal is accepted.
- Risk controls: enforced server-side before queueing an order.
- Mobile: Expo Router; the app is designed to reconnect after returning to the foreground.

## Deployment

The backend entrypoint is `backend/main.py`, which exports `app.main:app`. The configured production health endpoint is `https://tradeguard-api.fastapicloud.dev/health`.

Required secrets are configured in the deployment environment, not in this repository. At minimum, configure the cTrader client ID and secret, token-encryption key, app session secret, and database connection string. Never commit broker credentials or access/refresh tokens.

## Verification

Run the mobile typecheck with `npm run typecheck`. Run backend unit tests from the `backend` directory with `python -m unittest discover -s tests -p 'test_*.py' -v` when a test suite is present. Test cTrader order execution against a Demo account before any production Live-order capability is enabled.
