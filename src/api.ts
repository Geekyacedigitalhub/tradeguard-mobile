import * as SecureStore from "expo-secure-store";

const API_BASE_URL = process.env.EXPO_PUBLIC_API_URL ?? "https://tradeguard-api.fastapicloud.dev";
const TOKEN_KEY = "tradeguard_token";

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
      let message = raw;
      try {
        const parsed = JSON.parse(raw);
        message = parsed?.detail ?? parsed?.message ?? raw;
      } catch {}
      throw new Error(message);
    }
    return await response.json() as T;
  } catch (error) {
    if (controller.signal.aborted) {
      throw new Error("TradeGuard API request timed out after 15 seconds. Check your connection and try again.");
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
let nextMarketStreamSubscriberId = 1;
const marketStreamSubscribers = new Map<number, MarketStreamSubscriber>();

function normalizeMarketSymbol(value: unknown): string {
  return String(value ?? "").toUpperCase().replace(/[^A-Z0-9]/g, "");
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
  marketStreamRetry = setTimeout(() => {
    marketStreamRetry = null;
    if (marketStreamToken === token && marketStreamSubscribers.size > 0) {
      openMarketStream(token);
    }
  }, 3000);
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
        return;
      }
      if (payload?.type !== "tick" || payload?.provider !== "ctrader" || !payload?.symbol) return;
      const key = normalizeMarketSymbol(payload.symbol);
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
  account: () => request("/v1/account"),
  me: () => request<{user:{id:string;email:string;display_name?:string|null}}>("/v1/auth/me"),
  ctraderOAuthStart: () => request<{authorization_url:string}>("/v1/ctrader/oauth/start"),
  ctraderStatus: () => request<any>("/v1/ctrader/oauth/status"),
  ctraderConnection: () => request<any>("/v1/ctrader/connection"),
  ctraderAccount: () => request<any>("/v1/ctrader/account"),
  ctraderAccounts: () => request<any>("/v1/ctrader/accounts"),
  ctraderSelectAccount: (account_id:number) => request<any>("/v1/ctrader/accounts/select",{method:"POST",body:JSON.stringify({account_id})}),
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
  knowledgeIndex: () => request("/v1/knowledge", undefined, false),
  knowledgeLibrary: () => request("/v1/knowledge/library", undefined, false),
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
  updateMode: (mode: string) => request("/v1/bot/mode", { method: "PUT", body: JSON.stringify({ mode }) }),
  aiApproval: () => request("/v1/bot/ai-approval"),
  updateAiApproval: (body: {enabled:boolean;min_score:number}) => request("/v1/bot/ai-approval", { method: "PUT", body: JSON.stringify(body) }),
  savePushToken: (token: string) => request<{ok:boolean;message?:string}>("/v1/notifications/token", { method: "POST", body: JSON.stringify({ token }) }),
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
  closeAll: () => request("/v1/trades/close-all", { method: "POST" })
};
