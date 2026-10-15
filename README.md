# TradeGuard Mobile

Native React Native + Expo trading control center.

## Architecture
- Mobile: React Native + Expo
- Backend: FastAPI
- Database: PostgreSQL / Neon
- Broker integration: cTrader Cloud only (demo phase)
- Trading modes: Signals Only and Semi-Auto; broker order execution remains locked until safety checks pass
- Risk controls enforced server-side

No broker secrets or live credentials belong in this repository.
