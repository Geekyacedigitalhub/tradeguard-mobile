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

## Bot console

The Autopilot tab is a live trading-bot console rather than a settings list:

- **Engine hero** — state (`MONITORING` / `IDLE` / `HALTED`), execution mode, a
  pulsing status LED, engine poll age and broker link health.
- **Account tape** — equity, balance, day P/L (UTC), unrealized P/L, open
  positions and drawdown, straight from the verified cTrader snapshot. Values
  are withheld (not guessed) when the snapshot is missing or older than 45s.
- **Risk envelope** — utilisation meters for open positions, drawdown and daily
  loss against the server-enforced limits, so you can see how close the bot is
  to tripping a guard.
- **AI approval layer** — arm/disarm auto-approval and set the minimum signal
  score (70–100) with explicit saves.
- **Protection profile** — edit risk per trade, daily loss limit, max open
  positions and max drawdown, applied through `PUT /v1/bot/risk` after a
  confirmation that restates every value.
- **Engine record and activity feed** — journal win rate / total R and the last
  eight alerts (signals, blocked entries, closes, emergency stops).
- **Control dock** — always-visible `START BOT` / `STOP BOT`, plus
  `STOP ALL` (emergency latch) and `CLOSE ALL`. While the emergency latch is
  set the primary control becomes `RESET LATCH`, because the backend rejects a
  start until the latch is cleared.

`ORDER ROUTING LOCKED` stays pinned on the console while broker-verified volume
sizing is unavailable, so the interface never implies automated trading is live.

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
npm test
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

## Reinstall checklist

What is needed to build and install a fresh APK, in order.

**On your PC (one time)**

| Requirement | Version used by this project |
| --- | --- |
| Node.js | LTS (18+; CI uses 20/22) |
| JDK | 17 |
| Android SDK Platform | 35 |
| Android Build-Tools | 35.0.0 |
| Android Platform-Tools | for `adb` |
| Gradle | 8.14.3 (downloaded by the wrapper) |

The NDK is **not** required: the app ships no custom native code.

**Every rebuild**

```powershell
$env:EXPO_PUBLIC_API_URL = "https://your-backend-host"   # omit to use the built-in default
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\build-android-local.ps1 -Install
```

`EXPO_PUBLIC_*` values are inlined into the JavaScript bundle at build time, so
the API URL must be set in the same shell that runs the build. The script prints
the URL and the app version/versionCode it is about to build.

**Optional**

- `google-services.json` in the repository root (or `GOOGLE_SERVICES_JSON`
  pointing at it) to enable Expo push alerts. Without it the app still builds and
  runs; push registration reports `failed` and in-app alert history still works.
- Replace `assets/tradeguard-icon.png` with a 1024×1024 image for a sharper
  adaptive launcher icon (512×512 works but is slightly soft on high-DPI screens).

**After installing**

1. Sign in (or create an account).
2. Settings → **API LINK** → `TEST BACKEND CONNECTION` should report `REACHABLE`.
3. Settings → **CONNECT cTRADER** → finish authorization in the browser →
   `OPEN TRADEGUARD` → **REFRESH ACCOUNTS** → select a Demo account.
4. Cockpit and Positions should show broker equity/positions; Markets should show
   live ticks; Autopilot should show the account tape.

Run `npm run api:check -- --base-url <host> --email <you> --password <pw>` from
the computer first if step 2 fails.

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

- `npm run typecheck` passes with strict TypeScript, `npm test` renders the bot console in a jsdom-free React Native test environment, and `npx expo export --platform android` produces a production bundle.
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

## Status update — build readiness (2026-10-25)

Verified for reinstall:

- `npx expo prebuild --platform android` generates a clean native project (no
  warnings) with the `tradeguard://` deep link registered and no Firebase file
  required.
- `expo-doctor` reports 16/18 checks passing; the two failures are Expo/RN
  Directory API lookups blocked by this sandbox's network, not project issues.
- The native shell is branded dark (`backgroundColor`, splash, status bar and
  navigation bar all `#05090d`) instead of the default white flash.
- Version raised to **0.4.0 / versionCode 4** so a fresh install is recognised as
  newer than the previous build.
- Build script now prints the baked-in API base URL and the exact version it is
  about to build, and fails early if `npm ci` or Expo config validation fails.

## Status update — bot console (2026-10-25)

- Rebuilt the Autopilot tab as a live trading-bot console (engine state, account
  tape, risk utilisation meters, AI approval, protection editor, activity feed
  and a persistent control dock) on top of shared UI primitives in
  `src/components/ui.tsx`.
- Added `__tests__/bot-screen.test.tsx` (6 render tests): live metrics, activity
  feed, offline fallback, unselected account, emergency latch and stale-snapshot
  withholding. Wired into CI as `npm test`.
- Fixed two console bugs found during review: `START` was offered while the
  emergency latch was set (the API rejects it — the dock now offers
  `RESET LATCH`), and toggling AI approval discarded an edited score threshold.
