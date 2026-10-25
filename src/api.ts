import * as SecureStore from "expo-secure-store";
import type { BotMode } from "./api_mode";

const DEFAULT_API_BASE_URL = "https://tradeguard-api.fastapicloud.dev";
const CONFIGURED_API_BASE_URL = (process.env.EXPO_PUBLIC_API_URL ?? "").trim();
const TOKEN_KEY = "tradeguard_token";

/**
 * Normalize a configured base URL so generated paths never start with `//`
 * (a trailing slash would otherwise produce `https://host//v1/account`, which
 * the backend answers with a redirect or 404) and so a bare host such as
 * `api.example.com` still becomes a valid URL.
 */
export function normalizeApiBaseUrl(value: string): string {
  const trimmed = String(value ?? "").trim().replace(/\/+$/, "");
  if (!trimmed) return DEFAULT_API_BASE_URL;
  return /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
}

/** Resolved backend origin used by every HTTP and WebSocket call. */
export const API_BASE_URL = normalizeApiBaseUrl(CONFIGURED_API_BASE_URL || DEFAULT_API_BASE_URL);

/** Whether the URL came from EXPO_PUBLIC_API_URL or the built-in default. */
export const API_BASE_URL_SOURCE: "env" | "default" = CONFIGURED_API_BASE_URL ? "env" : "default";

/** API failure that keeps the HTTP status so screens can react to auth expiry. */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(message: string, status: number, detail?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export function isUnauthorized(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401;
}

/** HTTP status carried by an API failure, or null for network/timeout errors. */
export function apiErrorStatus(error: unknown): number | null {
  return error instanceof ApiError ? error.status : null;
}

type AuthFailureListener = () => void;
const authFailureListeners = new Set<AuthFailureListener>();

/**
 * Notified when the stored session is rejected by the backend (HTTP 401), so
 * the app shell can send the user back to the sign-in screen.
 */
export function onAuthFailure(listener: AuthFailureListener): () => void {
  authFailureListeners.add(listener);
  return () => { authFailureListeners.delete(listener); };
}

function notifyAuthFailure(): void {
  authFailureListeners.forEach(listener => {
    try { listener(); } catch {}
  });
}

function describeErrorPayload(parsed: unknown, raw: string): string {
  if (!parsed || typeof parsed !== "object") return raw;
  const detail = (parsed as any).detail ?? (parsed as any).message;
  if (typeof detail === "string") return detail;
  // FastAPI validation errors arrive as a list of field errors.
  if (Array.isArray(detail)) {
    const described = detail
      .map((item: any) => (typeof item?.msg === "string" ? item.msg : null))
      .filter((item: string | null): item is string => !!item);
    if (described.length) return described.join("; ");
  }
  if (detail != null) {
    try { return JSON.stringify(detail); } catch { return raw; }
  }
  return raw;
}

async function request<T>(path: string, init?: RequestInit, auth = true): Promise<T> {
  const token = auth ? await SecureStore.getItemAsync(TOKEN_KEY) : null;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(API_BASE_URL + path, {
      ...init,
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(init?.headers ?? {})
      }
    });
    if (!response.ok) {
      const raw = await response.text();
      let parsed: unknown = null;
      try { parsed = JSON.parse(raw); } catch {}
      const message = describeErrorPayload(parsed, raw) || `TradeGuard API returned HTTP ${response.status}`;
      if (response.status === 401 && auth) {
        // The stored session is expired or was revoked. Drop it so the next
        // launch (or the current screen) can send the user back to sign-in
        // instead of retrying with a token the backend will never accept.
        try { await SecureStore.deleteItemAsync(TOKEN_KEY); } catch {}
        notifyAuthFailure();
      }
      throw new ApiError(message, response.status, parsed ?? raw);
    }
    if (response.status === 204) return undefined as T;
    const body = await response.text();
    if (!body) return undefined as T;
    return JSON.parse(body) as T;
  } catch (error) {
    if (controller.signal.aborted) {
      throw new Error("TradeGuard API request timed out after 15 seconds. If this was a trading or close action, the outcome may be unknown; verify the cTrader account before retrying.");
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

type MarketStreamStatus = "LIVE" | "RECONNECTING" | "OFFLINE";
type MarketStreamSubscriber = {
  symbol: string;
  onTick: (tick: any) => void;
  onState?: (state: MarketStreamStatus) => void;
};

let marketStreamSocket: WebSocket | null = null;
let marketStreamToken: string | null = null;
let marketStreamRetry: ReturnType<typeof setTimeout> | null = null;
let marketStreamFailureCount = 0;
let nextMarketStreamSubscriberId = 1;
const marketStreamSubscribers = new Map<number, MarketStreamSubscriber>();

function normalizeMarketSymbol(value: unknown): string {
  return String(value ?? "").toUpperCase().replace(/[^A-Z0-9]/g, "");
}

function isFreshBrokerTimestamp(value: unknown, now = Date.now()): boolean {
  const raw = Number(value);
  if (!Number.isFinite(raw) || raw <= 0) return false;
  const timestampMs = raw > 100000000000 ? raw : raw * 1000;
  const ageMs = now - timestampMs;
  // Reject stale quotes and materially future-dated broker events.
  return ageMs <= 120000 && ageMs >= -30000;
}

function notifyMarketStreamState(state: MarketStreamStatus): void {
  marketStreamSubscribers.forEach(subscriber => {
    try { subscriber.onState?.(state); } catch {}
  });
}

function stopMarketStreamSocket(): void {
  if (marketStreamRetry) {
    clearTimeout(marketStreamRetry);
    marketStreamRetry = null;
  }
  marketStreamFailureCount = 0;
  const socket = marketStreamSocket;
  marketStreamSocket = null;
  if (socket) {
    socket.onopen = null;
    socket.onmessage = null;
    socket.onerror = null;
    socket.onclose = null;
    try { socket.close(); } catch {}
  }
}

function scheduleMarketStreamRetry(token: string): void {
  if (marketStreamRetry || marketStreamSubscribers.size === 0) return;
  // Back off on repeated failures (3s, 6s, 12s, 24s, then every 30s) so an
  // unavailable account or offline backend is not hammered every few seconds.
  // The delay resets as soon as a real tick or a new subscription arrives.
  const delay = Math.min(30000, 3000 * 2 ** Math.min(marketStreamFailureCount, 4));
  marketStreamFailureCount += 1;
  marketStreamRetry = setTimeout(() => {
    marketStreamRetry = null;
    if (marketStreamToken === token && marketStreamSubscribers.size > 0) {
      openMarketStream(token);
    }
  }, delay);
}

function openMarketStream(token: string): void {
  if (!token || marketStreamSocket || marketStreamSubscribers.size === 0) return;
  const wsBase = API_BASE_URL.replace(/^http:/, "ws:").replace(/^https:/, "wss:");
  notifyMarketStreamState("RECONNECTING");

  let socket: WebSocket;
  try {
    socket = new WebSocket(`${wsBase}/v1/ctrader/market-stream?token=${encodeURIComponent(token)}`);
  } catch {
    scheduleMarketStreamRetry(token);
    return;
  }
  marketStreamSocket = socket;

  // Opening a socket is not proof of market data. Subscribers turn LIVE only
  // after receiving a real quote for their own selected symbol.
  socket.onopen = () => {};
  socket.onmessage = event => {
    if (marketStreamSocket !== socket) return;
    try {
      const payload = JSON.parse(event.data);
      if (payload?.type === "stream_error") {
        notifyMarketStreamState("OFFLINE");
        // A stream-level error may arrive without the server closing the socket.
        // Close it explicitly so onclose can schedule the normal reconnect path.
        try { socket.close(); } catch {}
        return;
      }
      if (payload?.type !== "tick" || payload?.provider !== "ctrader" || !payload?.symbol) return;
      // A socket message is not proof of a usable quote. Keep the UI out of
      // LIVE state for malformed/empty prices or missing broker timestamps.
      const price = Number(payload.price);
      const tickTime = payload.time_msc ?? payload.time;
      if (!Number.isFinite(price) || price <= 0 || !isFreshBrokerTimestamp(tickTime)) return;
      const key = normalizeMarketSymbol(payload.symbol);
      marketStreamFailureCount = 0;
      marketStreamSubscribers.forEach(subscriber => {
        if (normalizeMarketSymbol(subscriber.symbol) !== key) return;
        try {
          subscriber.onTick(payload);
          subscriber.onState?.("LIVE");
        } catch {}
      });
    } catch {}
  };
  socket.onerror = () => {
    if (marketStreamSocket === socket) notifyMarketStreamState("RECONNECTING");
  };
  socket.onclose = () => {
    if (marketStreamSocket !== socket) return;
    marketStreamSocket = null;
    if (marketStreamSubscribers.size > 0 && marketStreamToken === token) {
      notifyMarketStreamState("RECONNECTING");
      scheduleMarketStreamRetry(token);
    } else {
      notifyMarketStreamState("OFFLINE");
    }
  };
}

function ensureMarketStream(token: string): void {
  if (marketStreamToken !== token) {
    stopMarketStreamSocket();
    marketStreamToken = token;
  }
  if (!marketStreamSocket && !marketStreamRetry) openMarketStream(token);
}

export const api = {
  register: (body: {email:string;password:string;display_name?:string}) => request<{token:string;user:any}>("/v1/auth/register",{method:"POST",body:JSON.stringify(body)},false),
  login: (body: {email:string;password:string}) => request<{token:string;user:any}>("/v1/auth/login",{method:"POST",body:JSON.stringify(body)},false),
  saveToken: (token:string) => SecureStore.setItemAsync(TOKEN_KEY, token),
  clearToken: () => SecureStore.deleteItemAsync(TOKEN_KEY),
  hasToken: () => SecureStore.getItemAsync(TOKEN_KEY),
  // Unauthenticated liveness probe: proves the app can reach the deployed
  // FastAPI process without needing a session or a cTrader account.
  health: () => request<{ok:boolean;service:string;time:string}>("/health", undefined, false),
  account: () => request("/v1/account"),
  me: () => request<{user:{id:string;email:string;display_name?:string|null}}>("/v1/auth/me"),
  ctraderOAuthStart: () => request<{authorization_url:string}>("/v1/ctrader/oauth/start"),
  ctraderStatus: () => request<any>("/v1/ctrader/oauth/status"),
  ctraderConnection: () => request<any>("/v1/ctrader/connection"),
  ctraderAccount: () => request<any>("/v1/ctrader/account"),
  ctraderAccounts: () => request<any>("/v1/ctrader/accounts"),
  ctraderSelectAccount: (account_id:number) => request<any>("/v1/ctrader/accounts/select",{method:"POST",body:JSON.stringify({account_id})}),
  closeAllCTraderPositions: () => request<any>("/v1/ctrader/positions/close-all", { method: "POST", body: JSON.stringify({ confirmation: "CLOSE_ALL" }) }),
  markets: () => request("/v1/markets"),
  marketCandles: (symbol:string, interval:"5m"|"15m"|"1h"="5m", limit=120) => request<any>(`/v1/markets/${encodeURIComponent(symbol)}/candles?interval=${interval}&limit=${limit}`),
  marketStream: async (onTick:(tick:any)=>void,onState?:(state:MarketStreamStatus)=>void,symbol="") => {
    const token = await SecureStore.getItemAsync(TOKEN_KEY);
    if (!token) {
      onState?.("OFFLINE");
      return () => {};
    }
    const id = nextMarketStreamSubscriberId++;
    const subscriber: MarketStreamSubscriber = { symbol, onTick, onState };
    marketStreamSubscribers.set(id, subscriber);
    ensureMarketStream(token);
    let active = true;
    return () => {
      if (!active) return;
      active = false;
      marketStreamSubscribers.delete(id);
      try { onState?.("OFFLINE"); } catch {}
      if (marketStreamSubscribers.size === 0) {
        stopMarketStreamSocket();
        marketStreamToken = null;
      }
    };
  },
  strategyBacktest: (symbol:string, interval:"5m"|"15m"|"1h"="15m") => request<any>(`/v1/strategy/backtest?symbol=${encodeURIComponent(symbol)}&interval=${interval}&limit=800`),
  strategyValidate: (symbol:string, costR=0) => request<any>(`/v1/strategy/validate?symbol=${encodeURIComponent(symbol)}&cost_r=${costR}&limit_5m=5000`),
  strategyLive: (symbol:string) => request<any>(`/v1/strategy/live?symbol=${encodeURIComponent(symbol)}`),
  strategyReviews: () => request<any>("/v1/strategy/reviews"),
  journal: (limit=50) => request<any>(`/v1/journal?limit=${limit}`),
  journalStats: () => request<any>("/v1/journal/stats"),
  addJournal: (body:any) => request<any>("/v1/journal",{method:"POST",body:JSON.stringify(body)}),
  deleteJournal: (id:number) => request<any>(`/v1/journal/${id}`,{method:"DELETE"}),
  signals: () => request("/v1/signals"),
  bot: () => request("/v1/bot"),
  startBot: () => request("/v1/bot/start", { method: "POST" }),
  stopBot: () => request("/v1/bot/stop", { method: "POST" }),
  updateMode: (mode: BotMode) => request("/v1/bot/mode", { method: "PUT", body: JSON.stringify({ mode }) }),
  aiApproval: () => request("/v1/bot/ai-approval"),
  updateAiApproval: (body: {enabled:boolean;min_score:number}) => request("/v1/bot/ai-approval", { method: "PUT", body: JSON.stringify(body) }),
  savePushToken: (token: string) => request<{ok:boolean;message?:string}>("/v1/notifications/token", { method: "POST", body: JSON.stringify({ token }) }),
  revokePushToken: () => request<{ok:boolean;registered:boolean}>("/v1/notifications/token", { method: "DELETE" }),
  notificationStatus: () => request<{registered:boolean;registered_at?:string|null;provider:string}>("/v1/notifications/status"),
  testNotification: () => request<{ok:boolean;message:string;provider:string;id?:string}>("/v1/notifications/test", { method: "POST" }),
  notificationEvents: () => request("/v1/notifications/events"),
  emergencyStop: () => request("/v1/bot/emergency-stop", { method: "POST" }),
  resetEmergency: () => request("/v1/bot/reset-emergency", { method: "POST" }),
  updateRisk: (body: unknown) => request("/v1/bot/risk", { method: "PUT", body: JSON.stringify(body) }),
  riskCheck: (signal: unknown) => request("/v1/risk/check", { method: "POST", body: JSON.stringify(signal) }),
  trades: (status?: string) => request(`/v1/trades${status ? `?status=${status}` : ""}`),
  openTrade: (signal: unknown) => request<any>("/v1/trades/open", { method: "POST", body: JSON.stringify(signal) }),
  bridgeCommand: (id: number) => request<any>(`/v1/trades/command/${id}`),
  closeTrade: (id: number) => request(`/v1/trades/${id}/close`, { method: "POST" }),
  closeCTraderPosition: (positionId: number, volume: number) => request<any>(`/v1/trades/ctrader/${positionId}/close`, { method: "POST", body: JSON.stringify({ volume }) }),
  cTraderCommand: (id: number) => request<any>(`/v1/trades/ctrader/command/${id}`),
  closeAll: () => request<any>("/v1/ctrader/positions/close-all", { method: "POST", body: JSON.stringify({ confirmation: "CLOSE_ALL" }) })
};
