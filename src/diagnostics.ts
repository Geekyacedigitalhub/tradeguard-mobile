import { Platform, ErrorUtils } from "react-native";
import Constants from "expo-constants";

const API_BASE = process.env.EXPO_PUBLIC_API_URL ?? "https://tradeguard-api.fastapicloud.dev";

export function deviceInfo() {
  const c: any = (Platform as any).constants ?? {};
  const extra: any = (Constants as any).extra ?? {};
  return {
    app: "tradeguard-mobile",
    app_version: (Constants as any).expoConfig?.version ?? (Constants as any).appVersion ?? "unknown",
    build: (Constants as any).appBuild ?? (Constants as any).nativeAppBuild ?? null,
    package: c.bundleIdentifier ?? c.package ?? extra?.android?.package ?? null,
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

  // Capture unhandled promise rejections too — in release these are reported as
  // fatal by Hermes but otherwise produce no visible crash log.
  try {
    const g: any = globalThis;
    if (typeof g.addEventListener === "function") {
      g.addEventListener("unhandledrejection", (e: any) => {
        const reason = e?.reason;
        report("js_error", {
          fatal: true,
          unhandled_rejection: true,
          message: String(reason?.message ?? reason ?? "unknown"),
          stack: reason?.stack ?? null
        });
      });
    }
  } catch {}

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
