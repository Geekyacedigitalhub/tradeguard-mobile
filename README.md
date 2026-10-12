# TradeGuard Mobile

TradeGuard is a React Native + Expo trading control center with a FastAPI cloud backend.

## Current architecture
- **Mobile:** React Native, Expo Router, TypeScript
- **API:** FastAPI, Python 3.12
- **Database:** PostgreSQL
- **Broker integration:** cTrader Open API OAuth + cloud connection
- **Market stream:** authenticated WebSocket backed by cTrader spot subscriptions
- **Risk gates:** server-side validation, risk checks, and demo-only automated order path
- **CI:** GitHub Actions runs mobile TypeScript checks and backend compilation

## cTrader configuration
Configure these variables in the backend deployment environment; do not commit broker secrets:
- `CTRADER_CLIENT_ID`
- `CTRADER_CLIENT_SECRET`
- `CTRADER_REDIRECT_URI` (must match the redirect URI registered with cTrader)
- `DATABASE_URL`
- `JWT_SECRET`

Token encryption currently derives its key from `JWT_SECRET`. Keep this value stable across deployments so previously stored OAuth tokens remain decryptable.

## Verification and safety
- GitHub Actions checks compilation and TypeScript; a green workflow is not a substitute for connecting a real authorized cTrader account.
- The live account is exposed for account viewing, but automated order execution is guarded to Demo accounts.
- cTrader order processing requires a broker-validated `broker_volume`; the worker intentionally rejects entries when exact symbol/account sizing is not available. Do not remove this guard by guessing a lot size.
- A running backend health endpoint confirms process availability only; it does not prove OAuth, streamed ticks, account balance refresh, or order placement work.

## Known gaps
- Reconcile the existing draft completion branch with `main` before merging it. It has diverged substantially; do not merge it as-is.
- Complete cTrader symbol-specific risk sizing and validate demo orders with a broker-authorized account.
- Confirm the deployed FastAPI Cloud service is using the latest `main` revision. The Render service registered for this repository is suspended and should not be treated as the active API deployment.
- Device-level testing is still required for app background/resume behavior, account display, and quote freshness.

## Status update — 2026-10-12

- Latest `main` CI passed mobile TypeScript and backend compile checks at commit `51df0423fac296d9033dbe435de898b5189617fa` and the subsequent documentation update.
- PR #4 remains a draft and must not be merged without reconciliation; it has diverged substantially from `main`.
- Account currency lookup was not verified against the installed cTrader SDK and was backed out. The account response still reports `currency: null`; today P/L and drawdown also remain unavailable rather than using fabricated values.
- The cTrader command worker intentionally refuses automated orders when broker-calculated `broker_volume` is absent. Implement symbol-specific risk sizing and prove it with authorized Demo orders before describing auto-trading as complete.
- The Render service registered for this repository is suspended, with the last live deployment pointing to an October 4 commit. The intended FastAPI Cloud revision could not be confirmed from this connection.
- Live account viewing is supported in code, but execution is restricted to Demo. OAuth, fresh broker ticks, account refresh and SL/TP behavior still require a broker-authorized test; physical Android background/resume and quote freshness are also unverified.
- PR #5 was closed unmerged because its account-currency enhancement could not be verified.

Do not mark TradeGuard as complete until deployment revision, cTrader account/market-data integration, symbol-specific sizing, and Android verification have all passed.
