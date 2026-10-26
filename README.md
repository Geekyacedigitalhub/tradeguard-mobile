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

## Install options

### 1) Installable web app (PWA) — fastest
The web build is a fully installable Progressive Web App: manifest, service worker, icons and offline shell are included.

- **Android/Chrome:** open the app in Chrome and use the "Install TradeGuard" banner (or the install icon in the address bar).
- **iPhone/iPad (Safari):** open the app, tap Share → "Add to Home Screen". It launches full-screen like a native app.

Once installed it works offline (app shell) and keeps showing the last good API data if the network drops. No store account is required.

### 2) Android debug APK via GitHub Actions
A CI workflow (`.github/workflows/android-apk.yml`) builds a real Android APK on every push/PR to `main` and on demand:

1. In the GitHub UI open **Actions → Android APK → Run workflow** (or wait for a push to `main`).
2. When the run is green, open its **Artifacts** tab and download `tradeguard-android-debug-apk`.
3. On `main` the APK is also attached to a GitHub **Release** automatically.

Install the APK on a device with "Install unknown apps" enabled. This is a debug-signed build for testing — not for Play Store distribution.

The APK always points at the production API endpoint (`EXPO_PUBLIC_API_URL` default); to target another backend, export the variable before the prebuild step.

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
