// The very first module executed by the app (imported by entry.ts before
// anything else). Sends a fire-and-forget "js_started" beacon to the demo
// backend so we can distinguish:
//   - no beacon at all            -> the app died before JavaScript ran
//                                    (native-level startup crash)
//   - js_started, then nothing    -> JavaScript started, then died during
//                                    router/initial-render setup
//   - js_started + launch/error   -> the app reached the root layout;
//                                    further events identify the failure
// This module has no dependencies and cannot throw.
export {};

try {
  const base =
    process.env.EXPO_PUBLIC_API_URL ??
    "https://tradeguard-api.fastapicloud.dev";
  (globalThis as any).fetch?.(base + "/v1/diagnostic", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ event: "js_started", at: new Date().toISOString() }),
    keepalive: true
  });
} catch {}
