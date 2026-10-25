import { API_BASE_URL, API_BASE_URL_SOURCE } from "./api";

export type BackendLink = {
  /** True only when the backend answered 200 with `ok: true`. */
  ok: boolean;
  baseUrl: string;
  source: "env" | "default";
  latencyMs: number | null;
  status: number | null;
  service: string | null;
  serverTime: string | null;
  message: string;
};

const PROBE_TIMEOUT_MS = 8000;

/**
 * Probe the deployed FastAPI service from the device.
 *
 * This is deliberately independent of the session and of cTrader: a successful
 * probe proves DNS/TLS/network reachability and that the running process is
 * TradeGuard's backend, nothing more. Broker authorization is a separate check
 * on the cTrader panels.
 */
export async function probeBackend(): Promise<BackendLink> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), PROBE_TIMEOUT_MS);
  const startedAt = Date.now();

  const base = {
    baseUrl: API_BASE_URL,
    source: API_BASE_URL_SOURCE,
  };

  try {
    const response = await fetch(`${API_BASE_URL}/health`, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: controller.signal,
    });
    const latencyMs = Date.now() - startedAt;

    let payload: any = null;
    try { payload = await response.json(); } catch {}

    if (!response.ok) {
      return {
        ...base,
        ok: false,
        latencyMs,
        status: response.status,
        service: typeof payload?.service === "string" ? payload.service : null,
        serverTime: typeof payload?.time === "string" ? payload.time : null,
        message: `The backend answered HTTP ${response.status} instead of a healthy response. Check that EXPO_PUBLIC_API_URL points at the TradeGuard API rather than a proxy or dashboard.`,
      };
    }

    if (payload?.ok !== true) {
      return {
        ...base,
        ok: false,
        latencyMs,
        status: response.status,
        service: typeof payload?.service === "string" ? payload.service : null,
        serverTime: typeof payload?.time === "string" ? payload.time : null,
        message: "The URL responded, but not with TradeGuard's health payload. It is probably a different service.",
      };
    }

    return {
      ...base,
      ok: true,
      latencyMs,
      status: response.status,
      service: typeof payload.service === "string" ? payload.service : null,
      serverTime: typeof payload.time === "string" ? payload.time : null,
      message: "Backend reachable and reporting healthy. Broker authorization and market data still need their own checks.",
    };
  } catch (error: any) {
    const aborted = controller.signal.aborted;
    return {
      ...base,
      ok: false,
      latencyMs: null,
      status: null,
      service: null,
      serverTime: null,
      message: aborted
        ? `No response within ${PROBE_TIMEOUT_MS / 1000} seconds. The service may be suspended or the network is blocking it.`
        : `Could not reach the backend (${String(error?.message ?? "network error")}). Check the phone's connection and EXPO_PUBLIC_API_URL.`,
    };
  } finally {
    clearTimeout(timer);
  }
}
