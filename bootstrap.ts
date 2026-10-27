// The very first module executed by the app (imported by entry.ts before
// anything else). It does three things, in order:
//
//   1. Opens a new session in the ON-DEVICE crash journal (a plain file,
//      written synchronously). This is the black box: if the app dies before
//      any network call ever succeeds, the file still contains everything the
//      JS runtime recorded up to the moment of death.
//   2. Installs global error handlers (unhandled rejections, window errors,
//      ErrorUtils) so the journal captures the exact error + stack.
//   3. Fires a best-effort "js_started" beacon to the backend (only useful
//      while the backend is reachable; the journal is the primary channel).
//
// Every diagnostic import goes through require() inside try/catch so a
// failure in the diagnostic code can NEVER prevent the app from starting.

// Metro's CommonJS require; typed locally to keep this file dependency-free.
declare const require: (id: string) => any;

const BASE =
  process.env.EXPO_PUBLIC_API_URL ??
  "https://tradeguard-api.fastapicloud.dev";

const meta: Record<string, unknown> = {
  app_version: "0.4.5",
  api_base: BASE,
  react: (globalThis as any).ReactNativeVersionString ?? null,
  platform: "android"
};

try {
  const { initJournal, jstage } = require("./src/crashjournal");
  initJournal(meta);
  jstage("js_started");
  const { installErrorHandlers } = require("./src/diagnostics");
  installErrorHandlers();
} catch {}

try {
  (globalThis as any).fetch?.(BASE + "/v1/diagnostic", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ event: "js_started", at: new Date().toISOString(), ...meta }),
    keepalive: true
  });
} catch {}

export {};
