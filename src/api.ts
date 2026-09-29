import * as SecureStore from "expo-secure-store";

const API_BASE_URL = process.env.EXPO_PUBLIC_API_URL ?? "https://tradeguard-api-ajyx.onrender.com";
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
  if (!response.ok) throw new Error(await response.text());
  return response.json() as Promise<T>;
}

export const api = {
  register: (body: {email:string;password:string;display_name?:string}) => request<{token:string;user:any}>("/v1/auth/register",{method:"POST",body:JSON.stringify(body)},false),
  login: (body: {email:string;password:string}) => request<{token:string;user:any}>("/v1/auth/login",{method:"POST",body:JSON.stringify(body)},false),
  saveToken: (token:string) => SecureStore.setItemAsync(TOKEN_KEY, token),
  clearToken: () => SecureStore.deleteItemAsync(TOKEN_KEY),
  hasToken: () => SecureStore.getItemAsync(TOKEN_KEY),
  account: () => request("/v1/account"),
  markets: () => request("/v1/markets"),
  signals: () => request("/v1/signals"),
  bot: () => request("/v1/bot"),
  startBot: () => request("/v1/bot/start", { method: "POST" }),
  stopBot: () => request("/v1/bot/stop", { method: "POST" }),
  emergencyStop: () => request("/v1/bot/emergency-stop", { method: "POST" }),
  resetEmergency: () => request("/v1/bot/reset-emergency", { method: "POST" }),
  updateRisk: (body: unknown) => request("/v1/bot/risk", { method: "PUT", body: JSON.stringify(body) }),
  riskCheck: (signal: unknown) => request("/v1/risk/check", { method: "POST", body: JSON.stringify(signal) }),
  trades: (status?: string) => request(`/v1/trades${status ? `?status=${status}` : ""}`),
  closeTrade: (id: number) => request(`/v1/trades/${id}/close`, { method: "POST" }),
  closeAll: () => request("/v1/trades/close-all", { method: "POST" })
};
