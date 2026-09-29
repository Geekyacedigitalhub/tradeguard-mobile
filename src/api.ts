const API_BASE_URL = process.env.EXPO_PUBLIC_API_URL ?? "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(API_BASE_URL + path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) }
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json() as Promise<T>;
}

export const api = {
  account: () => request("/v1/account"),
  markets: () => request("/v1/markets"),
  signals: () => request("/v1/signals"),
  bot: () => request("/v1/bot"),
  startBot: () => request("/v1/bot/start", { method: "POST" }),
  stopBot: () => request("/v1/bot/stop", { method: "POST" }),
  emergencyStop: () => request("/v1/bot/emergency-stop", { method: "POST" }),
  resetEmergency: () => request("/v1/bot/reset-emergency", { method: "POST" }),
  updateRisk: (body: unknown) => request("/v1/bot/risk", { method: "PUT", body: JSON.stringify(body) }),
  riskCheck: (signal: unknown) => request("/v1/risk/check", { method: "POST", body: JSON.stringify(signal) })
};
