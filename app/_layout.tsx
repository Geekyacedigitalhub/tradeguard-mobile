import React, { Component, useCallback, type ReactNode, useEffect, useState } from "react";
import { AppState, ScrollView, StyleSheet, Text, View, Pressable } from "react-native";
import { Stack } from "expo-router";
import Constants from "expo-constants";
import { installErrorHandlers, report, deviceInfo } from "../src/diagnostics";
import { readJournalText, readPreviousSession } from "../src/crashjournal";
import { colors } from "../src/theme";

type BoundaryState = { error?: Error; stack?: string | null };

function JournalText({ text, style }: { text: string; style?: object }) {
  return (
    <ScrollView style={[s.errBox, style]} nestedScrollEnabled>
      <Text style={s.errText}>{text}</Text>
    </ScrollView>
  );
}

class LaunchErrorBoundary extends Component<{ children: ReactNode }, BoundaryState> {
  state: BoundaryState = {};

  static getDerivedStateFromError(error: Error): BoundaryState {
    return { error, stack: error.stack ?? null };
  }

  componentDidCatch(error: Error, info: any) {
    report("render_error", {
      message: error?.message ?? String(error),
      stack: error?.stack ?? null,
      component_stack: info?.componentStackString ?? null
    });
  }

  render() {
    if (this.state.error) {
      let journal = "";
      try {
        journal = readJournalText();
      } catch {}
      return (
        <View style={s.errScreen}>
          <Text style={s.errLogo}>TRADEGUARD</Text>
          <Text style={s.errTitle}>Something went wrong</Text>
          <Text style={s.errSub}>
            This screen contains everything the app recorded before it failed —
            the full event log below. Take a screenshot and send it to the
            developer; that screenshot is exactly what is needed to fix it.
          </Text>
          <Text style={s.errLabel}>ERROR</Text>
          <Text style={s.errText}>
            {`${this.state.error?.message ?? this.state.error}\n${this.state.stack ?? ""}`}
          </Text>
          <Text style={s.errLabel}>EVENT LOG (this session)</Text>
          <JournalText text={journal} style={{ maxHeight: 220 }} />
        </View>
      );
    }
    return this.props.children;
  }
}

function CrashReportScreen({ report: prev, onDismiss }: { report: { lines: string[] }; onDismiss: () => void }) {
  const info = deviceInfo();
  const hadError = prev.lines.some((l) => /js_error|render_error/.test(l));
  return (
    <View style={s.errScreen}>
      <Text style={s.errLogo}>TRADEGUARD</Text>
      <Text style={s.errTitle}>Last session ended unexpectedly</Text>
      <Text style={s.errSub}>
        {hadError
          ? "The app recorded an error before it stopped. Screenshot this screen (scroll down if needed) and send it to the developer."
          : "No explicit error was recorded — the app may have been force-stopped by the system or you. Screenshot this screen and send it to the developer either way; the event log shows exactly how far it got."}
      </Text>
      <Text style={s.errLabel}>DEVICE / BUILD</Text>
      <Text style={s.errText}>
        {`${info.brand} ${info.model} · Android ${info.os_version} · app v${info.app_version} (build ${info.build ?? "?"})\napi: ${info.api_base}`}
      </Text>
      <Text style={s.errLabel}>EVENT LOG (previous session)</Text>
      <JournalText text={prev.lines.join("\n") || "(empty)"} style={{ flex: 1 }} />
      <Pressable style={s.dismissBtn} onPress={onDismiss}>
        <Text style={s.dismissText}>Open the app anyway</Text>
      </Pressable>
    </View>
  );
}

export default function RootLayout() {
  // Read the previous session synchronously before the first render.
  const [prevSession] = useState(() => {
    try {
      const prev = readPreviousSession();
      return prev && !prev.clean ? prev : null;
    } catch {
      return null;
    }
  });
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    report("root_layout_mounted");
    const hb = setInterval(() => {
      report("heartbeat");
    }, 10000);
    const onState = (state: string) => {
      if (state === "background") report("session_end", { state });
    };
    const sub = AppState.addEventListener("change", onState);
    return () => {
      clearInterval(hb);
      sub.remove();
    };
  }, []);

  const dismiss = useCallback(() => setDismissed(true), []);

  return (
    <LaunchErrorBoundary>
      {prevSession && !dismissed ? (
        <CrashReportScreen report={prevSession} onDismiss={dismiss} />
      ) : (
        <Stack screenOptions={{ headerShown: false }} />
      )}
    </LaunchErrorBoundary>
  );
}

const s = StyleSheet.create({
  errScreen: { flex: 1, backgroundColor: colors.background, padding: 20 },
  errLogo: { color: colors.green, fontSize: 15, fontWeight: "900", letterSpacing: 2 },
  errTitle: { color: colors.text, fontSize: 22, fontWeight: "900", marginTop: 14 },
  errSub: { color: colors.muted, fontSize: 13, lineHeight: 19, marginTop: 8, marginBottom: 12 },
  errLabel: { color: colors.green, fontSize: 11, fontWeight: "900", letterSpacing: 1, marginTop: 10, marginBottom: 6 },
  errBox: { backgroundColor: colors.panel, borderColor: colors.border, borderWidth: 1, borderRadius: 12, padding: 12 },
  errText: { color: colors.amber, fontSize: 11, fontFamily: "monospace", lineHeight: 16 },
  dismissBtn: { marginTop: 14, backgroundColor: colors.green, borderRadius: 10, paddingVertical: 14, alignItems: "center" },
  dismissText: { color: "#04140c", fontSize: 14, fontWeight: "900" }
});
