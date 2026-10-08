import * as SecureStore from "expo-secure-store";

const API_BASE_URL = process.env.EXPO_PUBLIC_API_URL ?? "https://tradeguard-api.fastapicloud.dev";
const TOKEN_KEY = "tradeguard_token";

async function request<T>(path: string, init?: RequestInit, auth = true): Promise<T> {
  const token = auth ? await SecureStore.getItemAsync(TOKEN_KEY) : null;
  const response = await fetch(API_BASE_URL + path, {
    ...init,
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
  return response.json() as Promise<T>;
}

export const api = {
  register: (body: {email:string;password:string;display_name?:string}) => request<{token:string;user:any}>("/v1/auth/register",{method:"POST",body:JSON.stringify(body)},false),
  login: (body: {email:string;password:string}) => request<{token:string;user:any}>("/v1/auth/login",{method:"POST",body:JSON.stringify(body)},false),
  saveToken: (token:string) => SecureStore.setItemAsync(TOKEN_KEY, token),
  clearToken: () => SecureStore.deleteItemAsync(TOKEN_KEY),
  hasToken: () => SecureStore.getItemAsync(TOKEN_KEY),
  account: () => request("/v1/account"),
  me: () => request<{user:{id:string;email:string;display_name?:string|null}}>("/v1/auth/me"),
  broker: () => request("/v1/broker"),
  brokerSnapshot: () => request("/v1/broker/snapshot"),
  brokerHealth: () => request("/v1/broker/health"),
  mt5Connection: () => request("/v1/trades/connection"),
  pairBroker: (bridge_id="windows-mt5") => request("/v1/broker/pair",{method:"POST",body:JSON.stringify({bridge_id})}),
  createCloudEaBootstrap: () => request<{bridge_id:string;bootstrap_key:string}>("/v1/broker/ea-bootstrap",{method:"POST"}),
  markets: () => request("/v1/markets"),
  marketCandles: (symbol:string, interval:"5m"|"15m"|"1h"="5m", limit=120) => request<any>(`/v1/markets/${encodeURIComponent(symbol)}/candles?interval=${interval}&limit=${limit}`),
  marketStream: async (onTick:(tick:any)=>void,onState?:(state:"LIVE"|"RECONNECTING"|"OFFLINE")=>void) => {
    const token = await SecureStore.getItemAsync(TOKEN_KEY);
    if (!token) return () => {};
    const wsBase = API_BASE_URL.replace(/^http:/, "ws:").replace(/^https:/, "wss:");
    let stopped = false;
    let socket: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout> | null = null;
    const connect = () => {
      if (stopped) return;
      onState?.("RECONNECTING");
      socket = new WebSocket(`${wsBase}/v1/market-stream?token=${encodeURIComponent(token)}`);
      socket.onopen = () => onState?.("LIVE");
      socket.onmessage = event => {
        try {
          const payload = JSON.parse(event.data);
          if (payload?.type === "tick" && payload.tick) onTick(payload.tick);
        } catch {}
      };
      socket.onerror = () => onState?.("RECONNECTING");
      socket.onclose = () => {
        socket = null;
        if (!stopped) {
          onState?.("RECONNECTING");
          retry = setTimeout(connect, 2000);
        }
      };
    };
    connect();
    return () => {
      stopped = true;
      if (retry) clearTimeout(retry);
      try { socket?.close(); } catch {}
      socket = null;
      onState?.("OFFLINE");
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
  switchBrokerAccount: (profile:"demo"|"live", confirmation?:string) => request<any>("/v1/trades/account/switch",{method:"POST",body:JSON.stringify({profile,confirmation})}),
  closeTrade: (id: number) => request(`/v1/trades/${id}/close`, { method: "POST" }),
  closeMt5Trade: (ticket: number) => request(`/v1/trades/mt5/${ticket}/close`, { method: "POST" }),
  closeAll: () => request("/v1/trades/close-all", { method: "POST" })
};
