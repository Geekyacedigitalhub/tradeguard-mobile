import { Platform, ErrorUtils } from "react-native";

const API_BASE = process.env.EXPO_PUBLIC_API_URL ?? "https://tradeguard-api.fastapicloud.dev";

export function deviceInfo() {
  const c: any = (Platform as any).constants ?? {};
  return {
    app: "tradeguard-mobile",
    app_version: "0.3.3",
    package: "com.geekyacedigitalhub.tradeguard2",
    platform: Platform.OS,
    os_version: Platform.Version,
    brand: c.Brand ?? null,
    model: c.Model ?? null,
    react: (global as any).ReactNativeVersionString ?? null,
    api_base: API_BASE,
    dev: typeof __DEV__ !== "undefined" ? __DEV__ : null
  };
}

// Fire-and-forget report. Never throws, never blocks the UI.
export function report(event: string, payload: Record<string, unknown> = {}) {
  try {
    const body = JSON.stringify({ event, at: new Date().toISOString(), ...deviceInfo(), ...payload });
    // keepalive lets the OS deliver the POST even if the app is killed right after.
    fetch(API_BASE + "/v1/diagnostic", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
      keepalive: true
    }).catch(() => {});
  } catch {}
}

let installed = false;
export function installErrorHandlers() {
  if (installed) return;
  installed = true;
  try {
    const previous = ErrorUtils.getGlobalHandler?.() ?? null;
    ErrorUtils.setGlobalHandler((error: any, isFatal?: boolean) => {
      report("js_error", {
        fatal: isFatal,
        message: String(error?.message ?? error),
        stack: error?.stack ?? null
      });
      // Keep the default behavior (in debug builds this renders the red box).
      if (previous) {
        try {
          previous(error, isFatal);
          return;
        } catch {}
      }
    });
  } catch {}
}
