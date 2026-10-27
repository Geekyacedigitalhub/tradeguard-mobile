// App entry point (package.json "main").
//
// Order matters:
//   1. bootstrap.ts — opens the on-device crash journal session, installs
//      global error handlers, fires the js_started beacon.
//   2. If the PREVIOUS session died without a clean exit, register a plain
//      react-native crash-gate screen as the root INSTEAD of the router.
//      The gate uses only core react-native primitives, so it renders even
//      when the router/first-render path is exactly what is broken.
//   3. Otherwise load the normal router entry.
//
// The gate path lazy-requires the router (only when the user taps "Open the
// app anyway"), and if even loading the router's modules fails, a plain error
// screen shows the failure — still screenshot-able, still no router needed.
//
// IMPORTANT: no failure in the gate path may ever fall back to the router
// silently — that would reproduce the very white screen we are diagnosing.
// Every failure mode renders a screen the user can screenshot.

declare const require: (id: string) => any;

function fallbackRouter() {
  try {
    require("expo-router/entry");
  } catch {}
}

function showErrorScreen(label: string, error: any) {
  const React = require("react");
  const { AppRegistry, View, Text, ScrollView, StyleSheet } =
    require("react-native");
  let journal = "";
  try {
    journal = require("./src/crashjournal").readJournalText();
  } catch {}
  let text = String(error?.message ?? error);
  try {
    const st: string = error?.stack ?? "";
    if (st) text += "\n\n" + st.split("\n").slice(0, 14).join("\n");
  } catch {}
  const e = StyleSheet.create({
    root: { flex: 1, backgroundColor: "#160606", padding: 18 },
    title: { color: "#f87171", fontSize: 19, fontWeight: "900", marginTop: 8 },
    sub: { color: "#c9b8b8", fontSize: 13, lineHeight: 19, marginTop: 8, marginBottom: 10 },
    box: { flex: 1, backgroundColor: "#1f0b0b", borderColor: "#3a1d1d", borderWidth: 1, borderRadius: 12, padding: 12 },
    mono: { color: "#fbbf24", fontSize: 11, fontFamily: "monospace", lineHeight: 16 }
  });
  function ErrorRoot() {
    return (
      <View style={e.root}>
        <Text style={e.title}>{label}</Text>
        <Text style={e.sub}>
          Screenshot this screen and send it to the developer — the text
          below is exactly what is needed to fix it.
        </Text>
        <ScrollView style={e.box} nestedScrollEnabled>
          <Text style={e.mono}>{text + "\n\nJOURNAL:\n" + journal}</Text>
        </ScrollView>
      </View>
    );
  }
  AppRegistry.registerComponent("main", () => ErrorRoot);
}

try {
  // 1. journal + error handlers, as early as possible.
  require("./bootstrap");

  const { computeGate, GateScreen } = require("./src/crashgate");
  const gate = computeGate();

  if (gate.kind === "crash") {
    const React = require("react");
    const { AppRegistry, View, Text, ScrollView, StyleSheet, AppState } =
      require("react-native");
    const { jstage } = require("./src/crashjournal");

    try {
      AppState.addEventListener("change", (s: string) => {
        if (s === "background") jstage("session_end", { state: s, from: "crashgate" });
      });
    } catch (e) {
      jstage("gate_appstate_failed", { message: String((e as any)?.message ?? e) });
    }

    function ImportErrorScreen({ error }: { error: any }) {
      let text = String(error?.message ?? error);
      try {
        const st: string = error?.stack ?? "";
        if (st) text += "\n\n" + st.split("\n").slice(0, 12).join("\n");
      } catch {}
      return (
        <View style={e.root}>
          <Text style={e.title}>The app could not load its UI</Text>
          <Text style={e.sub}>
            Screenshot this screen and send it to the developer — the error
            below is exactly what is needed to fix it.
          </Text>
          <ScrollView style={e.box} nestedScrollEnabled>
            <Text style={e.mono}>{text}</Text>
          </ScrollView>
        </View>
      );
    }

    const e = StyleSheet.create({
      root: { flex: 1, backgroundColor: "#06120c", padding: 20 },
      title: { color: "#e8f5ee", fontSize: 20, fontWeight: "900", marginTop: 8 },
      sub: { color: "#8aa596", fontSize: 13, lineHeight: 19, marginTop: 8, marginBottom: 10 },
      box: { flex: 1, backgroundColor: "#0b1f16", borderColor: "#1d3a2c", borderWidth: 1, borderRadius: 12, padding: 12 },
      mono: { color: "#fbbf24", fontSize: 11, fontFamily: "monospace", lineHeight: 16 }
    });

    function GateRoot() {
      const [proceeding, setProceeding] = React.useState(false);
      if (!proceeding) {
        return (
          <GateScreen
            lines={gate.lines}
            onContinue={() => {
              jstage("gate_continue");
              setProceeding(true);
            }}
          />
        );
      }
      // Lazy: only load the router (and its whole module tree) now.
      let RouterApp: any = null;
      let loadError: any = null;
      try {
        ({ App: RouterApp } = require("expo-router/build/qualified-entry"));
      } catch (err) {
        loadError = err;
        try {
          require("./src/diagnostics").report("router_load_error", {
            message: String((err as any)?.message ?? err),
            stack: String((err as any)?.stack ?? "").slice(0, 2000)
          });
        } catch {}
        jstage("router_load_error", {
          message: String((err as any)?.message ?? err)
        });
      }
      if (loadError || !RouterApp) return <ImportErrorScreen error={loadError ?? new Error("router module missing")} />;
      return <RouterApp />;
    }

    AppRegistry.registerComponent("main", () => GateRoot);
    (globalThis as any).__TG_CRASHGATE__ = { active: true };
    jstage("gate_shown", { lines: gate.lines.length });
  } else {
    require("expo-router/entry");
  }
} catch (gateError) {
  // The gate must never block startup — but it must never fail SILENTLY
  // either. Show the failure on-screen (and record it in the journal) so a
  // gate bug can never masquerade as the router's white screen.
  try {
    require("./src/crashjournal").jstage("gate_branch_error", {
      message: String((gateError as any)?.message ?? gateError),
      stack: String((gateError as any)?.stack ?? "").slice(0, 2000)
    });
  } catch {}
  try {
    showErrorScreen("Crash-gate setup failed", gateError);
  } catch {
    fallbackRouter();
  }
}
