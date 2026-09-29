# TradeGuard MT5 Bridge

The bridge is a small Windows-side agent that runs beside MetaTrader 5.

## Responsibilities
- Authenticate to TradeGuard with `MT5_BRIDGE_SECRET`.
- Send periodic heartbeat messages.
- Poll `GET /v1/bridge/commands`.
- Execute only supported commands in the MT5 terminal.
- Report every command as completed or failed.
- Never expose broker credentials to the mobile app.

## Initial safety contract
The bridge starts in DEMO/PAPER mode. Live execution must be explicitly enabled and tested separately.

## Endpoints
- `POST /v1/bridge/heartbeat`
- `GET /v1/bridge/commands`
- `POST /v1/bridge/commands/result`

The actual MT5 terminal integration will be added after the bridge protocol is tested.
