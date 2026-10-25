# TradeGuard Mobile

TradeGuard is a React Native + Expo trading control center with a FastAPI cloud backend.

## Current architecture
- **Mobile:** React Native, Expo Router, TypeScript
- **API:** FastAPI, Python 3.12
- **Database:** PostgreSQL
- **Broker integration:** cTrader Open API OAuth + cloud connection
- **Market stream:** authenticated WebSocket backed by cTrader spot subscriptions
- **Risk gates:** server-side validation and risk checks, with automated entries blocked until broker-verified sizing exists
- **CI:** GitHub Actions runs mobile TypeScript checks and backend compilation

## Mobile API configuration
The app reads its backend URL from `EXPO_PUBLIC_API_URL`, falling back to
`https://tradeguard-api.fastapicloud.dev`. Copy `.env.example` to `.env` to point
a local build at another backend. `EXPO_PUBLIC_*` values are embedded in the
bundle, so never put secrets there.

## Verifying the mobile ↔ FastAPI connection

The app resolves its backend once, from `EXPO_PUBLIC_API_URL` (normalized: a
trailing slash or a bare host is handled), and falls back to
`https://tradeguard-api.fastapicloud.dev`.

Three ways to confirm the connection works:

1. **On the phone** — Settings → **API LINK** shows the resolved base URL, the
   HTTP status and latency of `/health`, and a **TEST BACKEND CONNECTION**
   button. `REACHABLE` proves the device can reach the FastAPI process; it does
   not prove a cTrader session.
2. **From a computer** — run the bundled smoke test against the deployment:

   ```bash
   npm run api:check -- --base-url https://your-api-host
   npm run api:check -- --base-url https://your-api-host --email you@example.com --password 'your-password'
   npm run api:check -- --base-url https://your-api-host --full
   ```

   It checks `/health`, the CORS preflight, anonymous rejection (401), sign-in,
   and the authenticated endpoints the app calls. A broker snapshot is reported
   as `SETUP` (not a failure) until an account is selected. Exit code is non-zero
   when anything actually fails.
3. **Backend tests** — `backend/tests/test_api_surface.py` asserts the same
   contract (health without auth, 401 on protected routes, CORS headers for
   browser clients, and the market-stream route being registered).

## Local verification
```bash
# Mobile
npm ci
npm run typecheck
npx expo export --platform android

# Backend (Python 3.12)
cd backend
python -m pip install -e .
python -m unittest discover -s tests -v
```

The backend test suite covers the risk gates, cTrader command worker,
close/verify flows, OAuth validation, money math, push notifications and the
cTrader-only account route. See `backend/README.md` for the API map and
environment variables.

## Build an Android APK locally on Windows

The Android APK can be built on your own Windows PC; an EAS build is not required.

1. Install Node.js LTS, a compatible JDK (JDK 17 for the current Expo/Gradle setup), and Android SDK platform/build tools.
2. Open PowerShell in the cloned repository. The script defaults to `C:\Android\Sdk`; pass `-SdkPath` if your SDK is elsewhere.
3. Run:

   ```powershell
   Set-ExecutionPolicy -Scope Process Bypass
   .\scripts\build-android-local.ps1
   ```

4. To install the newly built debug APK on a USB-debugging-enabled Android device:

   ```powershell
   .\scripts\build-android-local.ps1 -Install
   ```

5. To clean Gradle outputs before rebuilding:

   ```powershell
   .\scripts\build-android-local.ps1 -Clean
   ```

The APK output is `android\app\build\outputs\apk\debug\app-debug.apk`. The script runs `npm ci`, validates Expo configuration, generates the native Android project with Expo prebuild only if the Gradle wrapper is absent, and builds with local Gradle. It never submits an EAS cloud build. Keep Firebase configuration private; if you need push notifications, provide your own `google-services.json` or set `GOOGLE_SERVICES_JSON`.

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
- Live and Demo accounts are exposed for account viewing and manual broker-confirmed closes; automated order execution is blocked on both until broker-specific sizing is verified.
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
- Account currency is read from cTrader asset metadata when the broker returns it and otherwise reported as `null`; it has not been verified against a broker-authorized account. P/L and drawdown remain unavailable rather than using fabricated values when the broker data is incomplete.
- The cTrader command worker intentionally refuses automated orders when broker-calculated `broker_volume` is absent. Implement symbol-specific risk sizing and prove it with authorized Demo orders before describing auto-trading as complete.
- The Render service registered for this repository is suspended, with the last live deployment pointing to an October 4 commit. The intended FastAPI Cloud revision could not be confirmed from this connection.
- Live account viewing is supported in code, but automated execution is disabled for Demo and Live accounts. OAuth, fresh broker ticks, account refresh and SL/TP behavior still require a broker-authorized test; physical Android background/resume and quote freshness are also unverified.
- PR #5 was closed unmerged because its account-currency enhancement could not be verified.

Do not mark TradeGuard as complete until deployment revision, cTrader account/market-data integration, symbol-specific sizing, and Android verification have all passed.

## Status update — 2026-10-25

Verified in this revision:

- `npm run typecheck` passes with strict TypeScript, and `npx expo export --platform android` produces a production bundle.
- The backend compiles, `ruff check --select F,E9` is clean, and the full backend regression suite passes.
- Every `api.*` call in `src/api.ts` maps to a registered FastAPI route with the matching HTTP method (audited against `app.routes`), including the `/v1/ctrader/market-stream` WebSocket.

Corrected in this revision:

- The cloud-market-sync log line used a Python 3.12-only f-string, which raised `SyntaxError` on Python 3.11 toolchains.
- HTTP failures now carry their status: an expired session (401) clears the stored token and returns the app to sign-in instead of leaving every screen in an authorization-error state.
- Signing out revokes this phone's push token (`DELETE /v1/notifications/token`), so a signed-out device stops receiving that account's alerts.
- Push registration now passes the EAS `projectId` that current Expo SDKs require, runs from one shared module instead of two divergent copies, and re-checks when the app returns to the foreground.
- Market-stream reconnects use bounded backoff (3s → 30s) instead of retrying every three seconds forever.
- Stale documentation and `.env.example` now list the environment variables the backend actually requires.
- Added CORS middleware (`CORS_ALLOW_ORIGINS`, default `*`) so Expo web and browser tooling can call the API; bearer-token auth means a wildcard origin cannot leak a session.
- The API base URL is normalized (trailing slashes, bare hosts), the resolved URL is visible in Settings, and `npm run api:check` plus `backend/tests/test_api_surface.py` verify the deployed connection.
- The cTrader OAuth callback now returns a confirmation page with an `OPEN TRADEGUARD` deep link instead of a raw JSON body, so authorizing in the browser leads back into the app. `?format=json` keeps the JSON body for tooling.

Still requires external verification (not provable from code):

- Authorized cTrader OAuth for a Demo account, fresh streamed ticks, account snapshots and broker-confirmed position closes.
- Symbol-specific, account-currency risk sizing proven with Demo orders before automated entries can be enabled.
- Physical Android testing of background/resume behaviour, push delivery and quote freshness.
- Confirmation that the deployed FastAPI Cloud service runs this revision.

Do not mark TradeGuard as complete until those checks pass.
