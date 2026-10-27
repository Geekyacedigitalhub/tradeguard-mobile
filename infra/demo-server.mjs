// TradeGuard demo backend (PWA + APK demo mode).
// Serves the built web app from ../tradeguard-mobile/dist and implements the
// /v1 API surface the app expects, with an in-memory demo cTrader account.
//
// To run:  cd infra && npm init -y && npm i ws && node demo-server.mjs
// (a copy is also kept at /home/user/preview/server.mjs for the sandbox preview)
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { WebSocketServer } from "ws";

const DIST = process.env.TG_DIST || "/home/user/tradeguard-mobile/dist";
const PORT = Number(process.env.TG_PORT || 8081);

// ---------------------------------------------------------------------------
// Demo market data
// ---------------------------------------------------------------------------
const SYMBOLS = [
  { symbol: "EURUSD", name: "Euro / US Dollar", base: 1.0842, dec: 5 },
  { symbol: "GBPUSD", name: "Pound / US Dollar", base: 1.2865, dec: 5 },
  { symbol: "USDJPY", name: "US Dollar / Yen", base: 151.24, dec: 3 },
  { symbol: "XAUUSD", name: "Gold Spot", base: 2651.3, dec: 2 },
  { symbol: "BTCUSD", name: "Bitcoin / US Dollar", base: 97250, dec: 1 },
  { symbol: "ETHUSD", name: "Ethereum / US Dollar", base: 2915.4, dec: 2 },
  { symbol: "US30", name: "US 30 Cash Index", base: 42860, dec: 1 },
  { symbol: "UK100", name: "UK 100 Cash Index", base: 8245, dec: 1 }
];
const prices = Object.fromEntries(SYMBOLS.map((s) => [s.symbol, s.base]));
const opens = Object.fromEntries(SYMBOLS.map((s) => [s.symbol, s.base]));

function dec(sym) {
  return SYMBOLS.find((s) => s.symbol === sym)?.dec ?? 2;
}
function rnd(sym, vol) {
  const d = dec(sym);
  const next = prices[sym] * (1 + (Math.random() - 0.5) * vol);
  prices[sym] = Number(next.toFixed(d + 1));
  return prices[sym];
}

// ---------------------------------------------------------------------------
// In-memory state
// ---------------------------------------------------------------------------
const users = new Map(); // email -> {id,email,display_name,password}
const tokens = new Map(); // token -> user
const journalByUser = new Map();
const botByUser = new Map();
const notifByUser = new Map();
const diagnostics = [];

function userState(email) {
  if (!botByUser.has(email)) {
    botByUser.set(email, {
      running: false,
      mode: "signals_only",
      emergency_stopped: false,
      ai_approval: { enabled: true, min_score: 75 },
      risk: { max_risk_pct: 1, max_open_positions: 3, max_daily_loss_pct: 2 }
    });
  }
  if (!notifByUser.has(email)) {
    notifByUser.set(email, { registered: false, registered_at: null, events: [] });
  }
  if (!journalByUser.has(email)) {
    journalByUser.set(email, {
      nextId: 3,
      entries: [
        { id: 1, symbol: "XAUUSD", side: "SELL", notes: "Broke structure below London lows; covered at target 2.", created_at: new Date(Date.now() - 86400000).toISOString() },
        { id: 2, symbol: "EURUSD", side: "BUY", notes: "Range fade, +0.8R. Entry earlier than ideal.", created_at: new Date(Date.now() - 2 * 86400000).toISOString() }
      ]
    });
  }
  return { bot: botByUser.get(email), notif: notifByUser.get(email), journal: journalByUser.get(email) };
}

function seedDemoUser() {
  const email = "demo@tradeguard.app";
  if (!users.has(email)) {
    const u = { id: "u-demo", email, display_name: "Demo Trader", password: "demo1234" };
    users.set(email, u);
    const t = crypto.randomBytes(24).toString("hex");
    tokens.set(t, u);
  }
}
seedDemoUser();

function demoAccount() {
  const now = new Date().toISOString();
  const equity = 25412.86;
  return {
    connected: true,
    demo: true,
    environment: "demo",
    account_id: 100293847,
    name: "Demo 1",
    broker: "cTrader (demo gateway)",
    balance: 25231.42,
    equity,
    currency: "USD",
    margin_used: 1842.11,
    margin_level: 814.5,
    positions_count: 2,
    drawdown: -1.84,
    daily_drawdown: -0.42,
    today_pl: 54.31,
    updated_at: now,
    positions: [
      {
        id: 7001, symbol: "EURUSD", side: "BUY", volume: 0.5,
        open_price: 1.0811, current_price: prices.EURUSD,
        pl: Number((((prices.EURUSD - 1.0811) * 100000) * 0.5).toFixed(2)),
        opened_at: new Date(Date.now() - 3600000 * 5).toISOString()
      },
      {
        id: 7002, symbol: "XAUUSD", side: "SELL", volume: 1.0,
        open_price: 2658.9, current_price: prices.XAUUSD,
        pl: Number(((2658.9 - prices.XAUUSD) * 100 * 1.0).toFixed(2)),
        opened_at: new Date(Date.now() - 3600000 * 26).toISOString()
      }
    ]
  };
}

// ---------------------------------------------------------------------------
// HTTP plumbing
// ---------------------------------------------------------------------------
const server = http.createServer((req, res) => {
  const url = new URL(req.url, `http://${req.headers.host || "localhost"}`);
  const p = url.pathname;

  const json = (code, body) => {
    const data = JSON.stringify(body);
    res.writeHead(code, { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" });
    res.end(data);
  };

  if (req.method === "OPTIONS") {
    res.writeHead(204, {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type,Authorization"
    });
    return res.end();
  }

  // --- diagnostics (unauthenticated, fire-and-forget from the app) ---
  if (p === "/v1/diagnostic" && req.method === "POST") {
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", () => {
      let payload = {};
      try { payload = JSON.parse(body || "{}"); } catch {}
      diagnostics.push({ received_at: new Date().toISOString(), ...payload });
      if (diagnostics.length > 500) diagnostics.shift();
      console.log(`\n=== DIAGNOSTIC ${payload.event ?? "?"} (from ${req.headers["x-forwarded-for"] || req.socket.remoteAddress}) ===`);
      console.log(JSON.stringify(payload, null, 2));
      console.log("=== END DIAGNOSTIC ===\n");
      json(200, { ok: true });
    });
    return;
  }

  if (p.startsWith("/v1/")) {
    return handleApi(req, res, url, json);
  }

  // --- static web app with SPA fallback ---
  let file = p === "/" ? "/index.html" : p;
  const full = path.join(DIST, path.normalize(file).replace(/^([.][.][/\\])+/, ""));
  if (!full.startsWith(DIST)) return json(403, { detail: "forbidden" });
  fs.readFile(full, (err, buf) => {
    if (err) {
      fs.readFile(path.join(DIST, "index.html"), (e2, html) => {
        if (e2) return json(404, { detail: "web app not built yet" });
        res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
        res.end(html);
      });
      return;
    }
    const ext = path.extname(full);
    const types = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css", ".png": "image/png", ".svg": "image/svg+xml", ".json": "application/json", ".webmanifest": "application/manifest+json", ".ico": "image/x-icon" };
    res.writeHead(200, { "Content-Type": types[ext] || "application/octet-stream" });
    res.end(buf);
  });
});

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------
function handleApi(req, res, url, json) {
  const p = url.pathname;
  const m = req.method;
  let user = null;
  const auth = req.headers.authorization || "";
  if (auth.startsWith("Bearer ")) user = tokens.get(auth.slice(7)) || null;
  const needsAuth = !["/v1/auth/register", "/v1/auth/login"].includes(p);
  if (needsAuth && !user) return json(401, { detail: "Not authenticated" });

  const readBody = () =>
    new Promise((resolve) => {
      let body = "";
      req.on("data", (c) => (body += c));
      req.on("end", () => {
        try { resolve(body ? JSON.parse(body) : {}); } catch { resolve({}); }
      });
    });

  const route = async () => {
    if (p === "/v1/auth/register" && m === "POST") {
      const b = await readBody();
      const email = String(b.email || "").toLowerCase();
      if (!email || !/^[^@\s]+@[^@\s]+$/.test(email)) return json(400, { detail: "A valid email is required." });
      if (String(b.password || "").length < 8) return json(400, { detail: "Password must be at least 8 characters." });
      if (users.has(email)) return json(409, { detail: "An account with this email already exists." });
      const u = { id: "u-" + crypto.randomBytes(6).toString("hex"), email, display_name: b.display_name || email.split("@")[0], password: b.password };
      users.set(email, u);
      const t = crypto.randomBytes(24).toString("hex");
      tokens.set(t, u);
      return json(201, { token: t, user: { id: u.id, email: u.email, display_name: u.display_name } });
    }

    if (p === "/v1/auth/login" && m === "POST") {
      const b = await readBody();
      const u = users.get(String(b.email || "").toLowerCase());
      if (!u || u.password !== b.password) return json(401, { detail: "Invalid email or password." });
      const t = crypto.randomBytes(24).toString("hex");
      tokens.set(t, u);
      return json(200, { token: t, user: { id: u.id, email: u.email, display_name: u.display_name } });
    }

    if (p === "/v1/auth/me" && m === "GET") {
      return json(200, { user: { id: user.id, email: user.email, display_name: user.display_name } });
    }

    if (p === "/v1/account" && m === "GET") {
      const st = userState(user.email);
      const acc = demoAccount();
      return json(200, {
        broker: acc.broker, connected: true, demo: true,
        equity: acc.equity, balance: acc.balance, currency: acc.currency,
        margin_level: acc.margin_level,
        bot: {
          running: st.bot.running, mode: st.bot.mode,
          emergency_stopped: st.bot.emergency_stopped,
          ai_approval: st.bot.ai_approval
        },
        risk: st.bot.risk,
        updated_at: acc.updated_at
      });
    }

    if (p === "/v1/ctrader/account" && m === "GET") {
      return json(200, demoAccount());
    }
    if (p === "/v1/ctrader/connection" && m === "GET") {
      return json(200, { connected: true, environment: "demo", demo: true, updated_at: new Date().toISOString() });
    }
    if (p === "/v1/ctrader/accounts" && m === "GET") {
      const acc = demoAccount();
      return json(200, { accounts: [{ account_id: acc.account_id, name: acc.name, environment: acc.environment, currency: acc.currency, equity: acc.equity, selected: true }] });
    }
    if (p === "/v1/ctrader/accounts/select" && m === "POST") {
      return json(200, { ok: true, account_id: 100293847, selected: true });
    }
    if (p === "/v1/ctrader/oauth/start" && m === "GET") {
      return json(200, { authorization_url: "https://oauth.ctrader.com/demo" });
    }
    if (p === "/v1/ctrader/oauth/status" && m === "GET") {
      return json(200, { status: "connected", connected: true, environment: "demo", demo: true });
    }
    if (p === "/v1/ctrader/positions/close-all" && m === "POST") {
      const acc = demoAccount();
      const closed = (acc.positions || []).map((pos) => pos.symbol);
      return json(200, {
        ok: true, confirmed_closed: true, demo: true,
        closed_positions: closed, closed_count: closed.length,
        message: "Demo environment: positions were closed in simulation only. No real orders were sent.",
        command_ids: (acc.positions || []).map((pos) => pos.id + 100000)
      });
    }

    if (p === "/v1/markets" && m === "GET") {
      const now = Date.now();
      return json(200, SYMBOLS.map((s) => {
        const price = prices[s.symbol];
        const open = opens[s.symbol];
        const change = price - open;
        return {
          symbol: s.symbol, name: s.name,
          bid: Number((price * 0.99998).toFixed(s.dec)),
          ask: Number((price * 1.00002).toFixed(s.dec)),
          price, open, high: Math.max(price, open) * 1.0021, low: Math.min(price, open) * 0.9979,
          change: Number(change.toFixed(s.dec)),
          change_pct: Number(((change / open) * 100).toFixed(3)),
          volume: Math.round(1000 + Math.random() * 9000),
          time: new Date(now).toISOString(),
          demo: true
        };
      }));
    }

    let candlesMatch = p.match(/^\/v1\/markets\/([A-Za-z0-9]+)\/candles$/);
    if (candlesMatch && m === "GET") {
      const sym = candlesMatch[1].toUpperCase();
      const meta = SYMBOLS.find((s) => s.symbol === sym);
      if (!meta) return json(404, { detail: "Unknown symbol" });
      const interval = url.searchParams.get("interval") || "5m";
      const limit = Math.min(Number(url.searchParams.get("limit") || 120), 500);
      const stepMs = { "5m": 300000, "15m": 900000, "1h": 3600000 }[interval] || 300000;
      let seedVal = sym.split("").reduce((a, c) => a + c.charCodeAt(0), 0);
      const rand = () => { seedVal = (seedVal * 9301 + 49297) % 233280; return seedVal / 233280; };
      const candles = [];
      let close = meta.base * (1 - 0.004 * (rand() - 0.5));
      const start = Date.now() - limit * stepMs;
      for (let i = 0; i < limit; i++) {
        const o = close;
        close = close * (1 + (rand() - 0.5) * 0.0016);
        const hi = Math.max(o, close) * (1 + rand() * 0.0004);
        const lo = Math.min(o, close) * (1 - rand() * 0.0004);
        candles.push({
          time: new Date(start + i * stepMs).toISOString(),
          open: Number(o.toFixed(meta.dec)), high: Number(hi.toFixed(meta.dec)),
          low: Number(lo.toFixed(meta.dec)), close: Number(close.toFixed(meta.dec)),
          volume: Math.round(50 + rand() * 450)
        });
      }
      return json(200, { symbol: sym, interval, candles, demo: true });
    }

    if (p === "/v1/equity-history" && m === "GET") {
      const limit = Math.min(Number(url.searchParams.get("limit") || 48), 200);
      const end = 25412.86;
      let seedVal = 987654321;
      const rand = () => { seedVal = (seedVal * 9301 + 49297) % 233280; return seedVal / 233280; };
      const pts = [];
      let v = end;
      for (let i = 0; i < limit; i++) pts.push(v);
      for (let i = limit - 2; i >= 0; i--) {
        v = v / (1 + (rand() - 0.48) * 0.004);
        pts[i] = Number(v.toFixed(2));
      }
      return json(200, { points: pts, demo: true });
    }

    if (p === "/v1/strategy/backtest" && m === "GET") {
      const sym = (url.searchParams.get("symbol") || "EURUSD").toUpperCase();
      return json(200, {
        symbol: sym, interval: url.searchParams.get("interval") || "15m",
        profit_factor: 1.62, win_rate: 0.571, avg_r: 0.24,
        total_trades: 214, max_drawdown_pct: 4.8, sharpe: 1.21,
        expectancy: 38.4, period_days: 180,
        conclusion: "Edge persists out-of-sample on 15m bars. Costs included at 0.02R.",
        demo: true
      });
    }
    if (p === "/v1/strategy/validate" && m === "GET") {
      const sym = (url.searchParams.get("symbol") || "EURUSD").toUpperCase();
      return json(200, {
        symbol: sym, valid: true, checks_passed: 11, checks_failed: 0,
        warnings: ["Volatility regime shifted in the last 20 sessions; widen stops."],
        demo: true
      });
    }
    if (p === "/v1/strategy/live" && m === "GET") {
      const sym = (url.searchParams.get("symbol") || "EURUSD").toUpperCase();
      return json(200, {
        symbol: sym,
        signal: { action: "WAIT", strength: 42, confidence: 0.42, reason: "Momentum decaying into the NY session; no clean entry.", updated_at: new Date().toISOString() },
        intelligence: {
          rules: {
            name: "Liquidity Sweep Reclaim v3",
            regime: "trending_up",
            setup: "Break of session high after stop-hunt below equal lows",
            trigger: "5m close back above sweep high with volume expansion",
            protection: "SL below sweep low, R:R 1:2.5, max 1R daily"
          },
          score: 68, summary: "Trend intact but stretched; waiting for pullback to the 15m demand zone."
        },
        deep_analysis: {
          bias: "bullish", confluence: 3, key_levels: [
            { type: "support", price: Number((prices[sym] * 0.9965).toFixed(dec(sym))) },
            { type: "resistance", price: Number((prices[sym] * 1.0042).toFixed(dec(sym))) }
          ],
          narrative: "Price respected the weekly demand zone twice this week. Sellers are exhausting: RSI divergence on 15m while structure holds. Prefer longs on reclaims, invalidation below the zone.",
          updated_at: new Date().toISOString()
        },
        demo: true
      });
    }
    if (p === "/v1/strategy/reviews" && m === "GET") {
      return json(200, {
        reviews: [
          { id: 1, symbol: "XAUUSD", date: new Date(Date.now() - 86400000).toISOString(), outcome: "win", r: 1.4, note: "Sweep reclaim worked as modeled." },
          { id: 2, symbol: "EURUSD", date: new Date(Date.now() - 2 * 86400000).toISOString(), outcome: "loss", r: -0.9, note: "Late entry; stopped before the reclaim." },
          { id: 3, symbol: "BTCUSD", date: new Date(Date.now() - 3 * 86400000).toISOString(), outcome: "win", r: 2.1, note: "Strong continuation after funding flush." }
        ],
        demo: true
      });
    }

    if (p === "/v1/journal" && m === "GET") {
      const st = userState(user.email);
      return json(200, { entries: st.journal.entries, demo: true });
    }
    if (p === "/v1/journal/stats" && m === "GET") {
      const st = userState(user.email);
      const e = st.journal.entries;
      const wins = e.filter((x) => x.side).length;
      return json(200, { total: e.length, wins, losses: 0, win_rate: e.length ? wins / e.length : 0, demo: true });
    }
    if (p === "/v1/journal" && m === "POST") {
      const b = await readBody();
      const st = userState(user.email);
      const entry = {
        id: st.journal.nextId++,
        symbol: String(b.symbol || "UNKNOWN").toUpperCase(),
        side: b.side ? String(b.side).toUpperCase() : null,
        notes: String(b.notes || b.note || ""),
        r: b.r ?? null,
        created_at: new Date().toISOString()
      };
      st.journal.entries.unshift(entry);
      return json(201, { ok: true, entry, demo: true });
    }
    let journalDel = p.match(/^\/v1\/journal\/(\d+)$/);
    if (journalDel && m === "DELETE") {
      const st = userState(user.email);
      st.journal.entries = st.journal.entries.filter((e) => e.id !== Number(journalDel[1]));
      return json(200, { ok: true, demo: true });
    }

    if (p === "/v1/signals" && m === "GET") {
      return json(200, {
        signals: [
          { id: 1, symbol: "XAUUSD", side: "SELL", confidence: 0.71, reason: "Rejection at daily resistance + bearish divergence", created_at: new Date(Date.now() - 900000).toISOString() },
          { id: 2, symbol: "EURUSD", side: "BUY", confidence: 0.58, reason: "Liquidity sweep below Asia low", created_at: new Date(Date.now() - 3600000).toISOString() }
        ],
        demo: true
      });
    }

    if (p === "/v1/bot" && m === "GET") {
      const st = userState(user.email);
      return json(200, { ...st.bot, demo: true });
    }
    if (p === "/v1/bot/start" && m === "POST") {
      const st = userState(user.email);
      st.bot.running = true;
      return json(200, { ...st.bot, demo: true, message: "Bot started (demo simulation)." });
    }
    if (p === "/v1/bot/stop" && m === "POST") {
      const st = userState(user.email);
      st.bot.running = false;
      return json(200, { ...st.bot, demo: true, message: "Bot stopped." });
    }
    if (p === "/v1/bot/mode" && m === "PUT") {
      const b = await readBody();
      const st = userState(user.email);
      st.bot.mode = String(b.mode || st.bot.mode);
      return json(200, { ...st.bot, demo: true });
    }
    if (p === "/v1/bot/ai-approval" && m === "GET") {
      const st = userState(user.email);
      return json(200, { ...st.bot.ai_approval, demo: true });
    }
    if (p === "/v1/bot/ai-approval" && m === "PUT") {
      const b = await readBody();
      const st = userState(user.email);
      st.bot.ai_approval = { enabled: !!b.enabled, min_score: Number(b.min_score ?? st.bot.ai_approval.min_score) };
      return json(200, { ...st.bot.ai_approval, demo: true });
    }
    if (p === "/v1/bot/emergency-stop" && m === "POST") {
      const st = userState(user.email);
      st.bot.emergency_stopped = true;
      st.bot.running = false;
      st.notif.events.unshift({ id: crypto.randomUUID(), type: "emergency_stop", message: "Emergency stop engaged — all automated actions halted.", created_at: new Date().toISOString() });
      return json(200, { ...st.bot, demo: true, message: "Emergency stop engaged." });
    }
    if (p === "/v1/bot/reset-emergency" && m === "POST") {
      const st = userState(user.email);
      st.bot.emergency_stopped = false;
      return json(200, { ...st.bot, demo: true, message: "Emergency stop reset." });
    }
    if (p === "/v1/bot/risk" && m === "PUT") {
      const b = await readBody();
      const st = userState(user.email);
      st.bot.risk = { ...st.bot.risk, ...b };
      return json(200, { ...st.bot.risk, demo: true });
    }

    if (p === "/v1/risk/check" && m === "POST") {
      return json(200, { allowed: false, reason: "Demo environment: live risk gateway is disabled. Signals are evaluated but never routed to the broker.", demo: true });
    }

    if (p === "/v1/trades" && m === "GET") {
      const acc = demoAccount();
      return json(200, {
        trades: [
          { id: 7001, symbol: "EURUSD", side: "BUY", volume: 0.5, status: "open", open_price: 1.0811, current_price: prices.EURUSD, pl: acc.positions[0].pl, opened_at: acc.positions[0].opened_at },
          { id: 7002, symbol: "XAUUSD", side: "SELL", volume: 1.0, status: "open", open_price: 2658.9, current_price: prices.XAUUSD, pl: acc.positions[1].pl, opened_at: acc.positions[1].opened_at },
          { id: 6990, symbol: "BTCUSD", side: "LONG", volume: 0.1, status: "closed", open_price: 96100, close_price: 97480, pl: 138.0, opened_at: new Date(Date.now() - 86400000).toISOString(), closed_at: new Date(Date.now() - 82800000).toISOString() }
        ],
        demo: true
      });
    }
    if (p === "/v1/trades/open" && m === "POST") {
      return json(403, { detail: "Live order routing is disabled in the demo environment. The bot runs in signals-only mode; no real orders are placed.", demo: true });
    }
    let tradeClose = p.match(/^\/v1\/trades\/(\d+)\/close$/);
    if (tradeClose && m === "POST") {
      return json(200, { ok: true, confirmed_closed: true, trade_id: Number(tradeClose[1]), command_id: Number(tradeClose[1]) + 90000, demo: true, message: "Demo: close simulated." });
    }
    let cmdMatch = p.match(/^\/v1\/trades\/(ctrader\/)?command\/(\d+)$/);
    if (cmdMatch && m === "GET") {
      return json(200, { command_id: Number(cmdMatch[2]), status: "completed", result: { positions: [{ closed: true, simulated: true }] }, demo: true });
    }
    let ctrClose = p.match(/^\/v1\/trades\/ctrader\/(\d+)\/close$/);
    if (ctrClose && m === "POST") {
      return json(200, { ok: true, confirmed_closed: true, position_id: Number(ctrClose[1]), command_id: Number(ctrClose[1]) + 90000, demo: true, message: "Demo: position close simulated. No real order was sent." });
    }

    if (p === "/v1/notifications/token" && m === "POST") {
      const b = await readBody();
      const st = userState(user.email);
      st.notif.registered = true;
      st.notif.registered_at = new Date().toISOString();
      return json(200, { ok: true, registered: true, message: b.token ? "Push token stored (demo)." : "Demo: no token provided." });
    }
    if (p === "/v1/notifications/status" && m === "GET") {
      const st = userState(user.email);
      return json(200, { registered: st.notif.registered, registered_at: st.notif.registered_at, provider: "demo" });
    }
    if (p === "/v1/notifications/test" && m === "POST") {
      const st = userState(user.email);
      const ev = { id: crypto.randomUUID(), type: "test", message: "TradeGuard test notification (demo).", created_at: new Date().toISOString() };
      st.notif.events.unshift(ev);
      return json(200, { ok: true, message: "Test notification queued (demo).", provider: "demo", id: ev.id });
    }
    if (p === "/v1/notifications/events" && m === "GET") {
      const st = userState(user.email);
      if (st.notif.events.length === 0) {
        st.notif.events.push({ id: crypto.randomUUID(), type: "info", message: "Welcome to TradeGuard. The demo feed streams simulated market data.", created_at: new Date().toISOString() });
      }
      return json(200, { events: st.notif.events });
    }

    return json(404, { detail: `No demo route: ${m} ${p}` });
  };

  route().catch((e) => json(500, { detail: String(e?.message || e) }));
}

// ---------------------------------------------------------------------------
// WebSocket market stream: /v1/ctrader/market-stream?token=...
// ---------------------------------------------------------------------------
const wss = new WebSocketServer({ noServer: true });
server.on("upgrade", (req, socket, head) => {
  const url = new URL(req.url, `http://${req.headers.host || "localhost"}`);
  if (url.pathname !== "/v1/ctrader/market-stream") {
    socket.destroy();
    return;
  }
  const token = url.searchParams.get("token");
  const user = tokens.get(token || "");
  if (!user) {
    socket.destroy();
    return;
  }
  wss.handleUpgrade(req, socket, head, (ws) => {
    ws.isAlive = true;
    ws.on("pong", () => (ws.isAlive = true));
    wss.clients.add(ws);
    ws.send(JSON.stringify({ type: "hello", provider: "ctrader", demo: true, message: "Simulated demo feed" }));
    ws.on("close", () => wss.clients.delete(ws));
  });
});

let tickIndex = 0;
setInterval(() => {
  const sym = SYMBOLS[tickIndex % SYMBOLS.length];
  tickIndex++;
  const price = rnd(sym.symbol, sym.symbol.startsWith("BTC") || sym.symbol.startsWith("ETH") ? 0.0012 : 0.00035);
  const d = dec(sym.symbol);
  const payload = {
    type: "tick",
    provider: "ctrader",
    symbol: sym.symbol,
    price,
    bid: Number((price * 0.99998).toFixed(d)),
    ask: Number((price * 1.00002).toFixed(d)),
    spread: Number((price * 0.00004).toFixed(d)),
    volume: Math.round(10 + Math.random() * 200),
    time: new Date().toISOString(),
    time_msc: Date.now(),
    demo: true
  };
  const msg = JSON.stringify(payload);
  for (const client of wss.clients) {
    if (client.readyState === 1) client.send(msg);
  }
}, 750);

setInterval(() => {
  for (const client of wss.clients) {
    if (!client.isAlive) { client.terminate(); continue; }
    client.isAlive = false;
    client.ping();
  }
}, 30000);

server.listen(PORT, "0.0.0.0", () => {
  console.log(`TradeGuard demo backend listening on 0.0.0.0:${PORT}`);
  console.log(`Serving web app from ${DIST}`);
  console.log(`Demo login: demo@tradeguard.app / demo1234`);
});
