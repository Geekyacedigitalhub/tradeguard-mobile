#!/usr/bin/env node
/**
 * TradeGuard API smoke test.
 *
 * Verifies that the deployed FastAPI backend the mobile app talks to is
 * reachable and enforcing authentication correctly.
 *
 * Usage (Node 18+; no dependencies):
 *   node scripts/api-smoke-test.mjs
 *   node scripts/api-smoke-test.mjs --base-url https://tradeguard-api.fastapicloud.dev
 *   node scripts/api-smoke-test.mjs --email you@example.com --password 'your-password'
 *   node scripts/api-smoke-test.mjs --token <existing-session-token>
 *   node scripts/api-smoke-test.mjs --email new@example.com --password 'at-least-8' --register
 *   node scripts/api-smoke-test.mjs --full
 *
 * Flags:
 *   --base-url URL   Backend origin (default: EXPO_PUBLIC_API_URL or the built-in default)
 *   --token TOKEN    Reuse an existing session instead of logging in
 *   --email/--password   Sign in before running authenticated checks
 *   --register       Create the account instead of signing in (writes a real user row)
 *   --full           Also scan markets and load candles/strategy (slow on a small instance)
 *   --timeout MS     Per-request timeout (default: 20000, --full uses 90000 for /v1/markets)
 *
 * Exit code is 0 when every check passes or is legitimately "not configured".
 */

const DEFAULT_BASE_URL = "https://tradeguard-api.fastapicloud.dev";

function parseArgs(argv) {
  const options = {
    baseUrl: process.env.EXPO_PUBLIC_API_URL || DEFAULT_BASE_URL,
    token: null,
    email: null,
    password: null,
    register: false,
    full: false,
    timeout: 20000,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    const next = () => {
      const value = argv[index + 1];
      if (value === undefined || value.startsWith("--")) {
        throw new Error(`${arg} requires a value`);
      }
      index += 1;
      return value;
    };
    switch (arg) {
      case "--base-url": options.baseUrl = next(); break;
      case "--token": options.token = next(); break;
      case "--email": options.email = next(); break;
      case "--password": options.password = next(); break;
      case "--register": options.register = true; break;
      case "--full": options.full = true; break;
      case "--timeout": options.timeout = Number(next()); break;
      case "--help":
      case "-h":
        console.log("See the header of scripts/api-smoke-test.mjs for usage.");
        process.exit(0);
        break;
      default:
        throw new Error(`Unknown argument: ${arg}`);
    }
  }
  options.baseUrl = options.baseUrl.trim().replace(/\/+$/, "");
  if (!/^https?:\/\//i.test(options.baseUrl)) {
    options.baseUrl = `https://${options.baseUrl}`;
  }
  if (!Number.isFinite(options.timeout) || options.timeout <= 0) {
    throw new Error("--timeout must be a positive number of milliseconds");
  }
  return options;
}

const results = [];

function record(name, state, detail) {
  results.push({ name, state, detail });
  const prefix = state === "PASS" ? "PASS" : state === "SETUP" ? "SETUP" : state === "SKIP" ? "SKIP" : "FAIL";
  console.log(`${prefix.padEnd(5)}  ${name.padEnd(42)}  ${detail}`);
}

async function httpJson(baseUrl, path, { method = "GET", token, body, timeout = 20000, headers = {} } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  const startedAt = Date.now();
  try {
    const response = await fetch(`${baseUrl}${path}`, {
      method,
      headers: {
        Accept: "application/json",
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...headers,
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });
    const latencyMs = Date.now() - startedAt;
    const text = await response.text();
    let parsed = null;
    try { parsed = text ? JSON.parse(text) : null; } catch { parsed = null; }
    return { status: response.status, latencyMs, body: parsed, raw: text, headers: response.headers, error: null };
  } catch (error) {
    return {
      status: null,
      latencyMs: Date.now() - startedAt,
      body: null,
      raw: "",
      headers: null,
      error: controller.signal.aborted ? `timed out after ${timeout} ms` : String(error?.message || error),
    };
  } finally {
    clearTimeout(timer);
  }
}

function detailOf(response) {
  if (response.error) return response.error;
  const message = response.body?.detail ?? response.body?.message;
  if (typeof message === "string" && message) return `HTTP ${response.status} · ${message.slice(0, 90)}`;
  return `HTTP ${response.status}`;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  console.log(`\nTradeGuard API smoke test → ${options.baseUrl}\n`);

  // 1. Health is the only endpoint the app can call before sign-in.
  const health = await httpJson(options.baseUrl, "/health", { timeout: options.timeout });
  if (health.error) {
    record("GET /health", "FAIL", `cannot reach the backend · ${health.error}`);
  } else if (health.status === 200 && health.body?.ok === true) {
    record("GET /health", "PASS", `HTTP 200 · ${health.latencyMs} ms · service ${health.body.service ?? "unknown"}`);
  } else {
    record("GET /health", "FAIL", `${detailOf(health)} · not a TradeGuard health payload`);
  }

  // 2. Preflight must succeed for Expo web and browser tooling.
  const preflight = await httpJson(options.baseUrl, "/v1/account", {
    method: "OPTIONS",
    timeout: options.timeout,
    headers: {
      Origin: "https://tradeguard.example",
      "Access-Control-Request-Method": "GET",
      "Access-Control-Request-Headers": "authorization,content-type",
    },
  });
  const allowedOrigin = preflight.headers?.get("access-control-allow-origin");
  if (preflight.error) {
    record("CORS preflight /v1/account", "SKIP", preflight.error);
  } else if (allowedOrigin) {
    record("CORS preflight /v1/account", "PASS", `allow-origin: ${allowedOrigin}`);
  } else {
    record("CORS preflight /v1/account", "SKIP", "no CORS headers (fine for native apps, breaks Expo web)");
  }

  // 3. Protected routes must reject anonymous callers.
  const anonymous = await httpJson(options.baseUrl, "/v1/account", { timeout: options.timeout });
  if (anonymous.error) {
    record("GET /v1/account without a token", "FAIL", anonymous.error);
  } else if (anonymous.status === 401) {
    record("GET /v1/account without a token", "PASS", "HTTP 401 as expected");
  } else {
    record("GET /v1/account without a token", "FAIL", `${detailOf(anonymous)} · expected 401`);
  }

  let token = options.token;
  if (!token) {
    if (options.email && options.password) {
      const path = options.register ? "/v1/auth/register" : "/v1/auth/login";
      const body = options.register
        ? { email: options.email, password: options.password }
        : { email: options.email, password: options.password };
      const auth = await httpJson(options.baseUrl, path, { method: "POST", body, timeout: options.timeout });
      if (auth.error) {
        record(`POST ${path}`, "FAIL", auth.error);
      } else if (auth.status === 200 && typeof auth.body?.token === "string") {
        token = auth.body.token;
        record(`POST ${path}`, "PASS", `HTTP 200 · session issued for ${auth.body?.user?.email ?? options.email}`);
      } else {
        record(`POST ${path}`, "FAIL", detailOf(auth));
      }
    } else {
      record("Authenticated checks", "SKIP", "pass --email/--password or --token to run them");
    }
  }

  if (token) {
    const checks = [
      ["GET /v1/auth/me", "/v1/auth/me"],
      ["GET /v1/bot", "/v1/bot"],
      ["GET /v1/notifications/status", "/v1/notifications/status"],
      ["GET /v1/ctrader/oauth/status", "/v1/ctrader/oauth/status"],
      ["GET /v1/ctrader/connection", "/v1/ctrader/connection"],
      ["GET /v1/journal", "/v1/journal?limit=1"],
      ["GET /v1/journal/stats", "/v1/journal/stats"],
    ];
    for (const [name, path] of checks) {
      const response = await httpJson(options.baseUrl, path, { token, timeout: options.timeout });
      if (response.error) record(name, "FAIL", response.error);
      else if (response.status === 200) record(name, "PASS", `HTTP 200 · ${response.latencyMs} ms`);
      else if (response.status === 401) record(name, "FAIL", "HTTP 401 · the session token was rejected");
      else record(name, "FAIL", detailOf(response));
    }

    // The broker snapshot legitimately fails until an account is selected.
    const account = await httpJson(options.baseUrl, "/v1/ctrader/account", { token, timeout: options.timeout });
    if (account.error) record("GET /v1/ctrader/account", "FAIL", account.error);
    else if (account.status === 200 && account.body?.connected === true) {
      record("GET /v1/ctrader/account", "PASS", `HTTP 200 · ${account.body.environment ?? "?"} account ${account.body.account_id} · ${account.body.positions_count ?? "?"} position(s)`);
    } else if (account.status === 409 || account.status === 503) {
      record("GET /v1/ctrader/account", "SETUP", `no verified broker snapshot yet · ${detailOf(account)}`);
    } else {
      record("GET /v1/ctrader/account", "FAIL", detailOf(account));
    }

    if (options.full) {
      const markets = await httpJson(options.baseUrl, "/v1/markets", { token, timeout: Math.max(options.timeout, 90000) });
      if (markets.error) record("GET /v1/markets (scan)", "FAIL", markets.error);
      else if (markets.status === 200 && Array.isArray(markets.body)) {
        record("GET /v1/markets (scan)", "PASS", `HTTP 200 · ${markets.body.length} instruments · ${markets.latencyMs} ms`);
      } else {
        record("GET /v1/markets (scan)", "FAIL", detailOf(markets));
      }

      const candles = await httpJson(options.baseUrl, "/v1/markets/EURUSD/candles?interval=5m&limit=60", { token, timeout: options.timeout });
      if (candles.error) record("GET candles EURUSD 5m", "FAIL", candles.error);
      else if (candles.status === 200 && Array.isArray(candles.body?.candles) && candles.body.candles.length > 0) {
        record("GET candles EURUSD 5m", "PASS", `${candles.body.candles.length} candles`);
      } else {
        record("GET candles EURUSD 5m", "SETUP", detailOf(candles));
      }
    }
  }

  const passed = results.filter(item => item.state === "PASS").length;
  const failures = results.filter(item => item.state === "FAIL").length;
  const setup = results.filter(item => item.state === "SETUP").length;
  const skipped = results.filter(item => item.state === "SKIP").length;
  console.log(
    `\n${passed} passed · ${setup} awaiting account setup · ${skipped} skipped · ${failures} failed\n`,
  );
  if (failures > 0) {
    console.log("The app cannot rely on this backend until the failures above are resolved.\n");
    process.exitCode = 1;
  }
}

main().catch(error => {
  console.error(`\nSmoke test aborted: ${error?.message || error}\n`);
  process.exitCode = 1;
});
