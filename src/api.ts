import * as SecureStore from "expo-secure-store";

const API_BASE_URL = process.env.EXPO_PUBLIC_API_URL ?? "https://tradeguard-api.fastapicloud.dev";
const TOKEN_KEY = "tradeguard_token";

export class ApiError extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit, auth = true): Promise<T> {
  const token = auth ? await SecureStore.getItemAsync(TOKEN_KEY) : null;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 20000);
  try {
    const response = await fetch(API_BASE_URL + path, {
      ...init,
      signal: init?.signal ?? controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(init?.headers ?? {})
      }
    });
    if (!response.ok) {
      const raw = await response.text();
      let message = "The server could not complete the request.";
      try {
        const parsed = JSON.parse(raw);
        const detail = parsed?.detail ?? parsed?.message;
        if (typeof detail === "string" && detail.trim()) message = detail;
        else if (Array.isArray(detail)) message = detail.map((item:any) => item?.msg).filter(Boolean).join("; ") || message;
      } catch {}
      throw new ApiError(message, response.status);
    }
    return await response.json() as T;
  } catch (error:any) {
    if (error?.name === "AbortError") {
      throw new Error("The request timed out. Check your connection and try again.");
    }
    if (error instanceof TypeError) {
      throw new Error("Unable to reach TradeGuard. Check your internet connection and try again.");
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
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
  ctraderConnection: () => request("/v1/trades/connection"),
  ctraderOAuthStart: () => request<{authorization_url:string}>("/v1/ctrader/oauth/start"),
  ctraderStatus: () => request<any>("/v1/ctrader/oauth/status"),
  ctraderAccounts: () => request<any>("/v1/ctrader/accounts"),
  ctraderAccountSnapshot: () => request<any>("/v1/ctrader/account/snapshot"),
  ctraderSelectAccount: (account_id:number) => request<any>("/v1/ctrader/accounts/select",{method:"POST",body:JSON.stringify({account_id})}),
  markets: () => request("/v1/markets"),
  marketCandles: (symbol:string, interval:"5m"|"15m"|"1h"="5m", limit=120) => request<any>(`/v1/markets/${encodeURIComponent(symbol)}/candles?interval=${interval}&limit=${limit}`),
  marketStream: async (_onTick:(tick:any)=>void,onState?:(state:"LIVE"|"RECONNECTING"|"OFFLINE")=>void) => {
    // Tick streaming from the retired terminal bridge is intentionally disabled.
    // Candles continue to refresh through marketCandles until cTrader streaming is wired.
    onState?.("OFFLINE");
    return () => onState?.("OFFLINE");
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
  closeAll: () => request("/v1/trades/close-all", { method: "POST" })
};
