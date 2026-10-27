import React, { Component, type ReactNode, useEffect } from "react";
import { ScrollView, StyleSheet, Text, View } from "react-native";
import { Stack } from "expo-router";
import { installErrorHandlers, report } from "../src/diagnostics";
import { colors } from "../src/theme";

// Push notifications (expo-notifications) are intentionally NOT loaded in
// this build: the native module needs a Firebase project (google-services.json)
// and touching it on-device without one can crash the app at startup.
// Re-enable when Firebase is configured (see README).

type BoundaryState = { error?: Error; stack?: string | null };

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
      return (
        <View style={s.errScreen}>
          <Text style={s.errLogo}>TRADEGUARD</Text>
          <Text style={s.errTitle}>Something went wrong</Text>
          <Text style={s.errSub}>
            Tap the app icon to reopen. If it keeps happening, take a screenshot
            of this screen and send it to the developer — the error text below
            is exactly what is needed to fix it.
          </Text>
          <ScrollView style={s.errBox} nestedScrollEnabled>
            <Text style={s.errText}>
              {`ERROR: ${this.state.error.message ?? this.state.error}\n\n${this.state.stack ?? "no stack trace available"}`}
            </Text>
          </ScrollView>
        </View>
      );
    }
    return this.props.children;
  }
}

export default function RootLayout() {
  useEffect(() => {
    installErrorHandlers();
    // Launch beacon: if this arrives on the server, JS started successfully.
    report("launch");
  }, []);

  return (
    <LaunchErrorBoundary>
      <Stack screenOptions={{ headerShown: false }} />
    </LaunchErrorBoundary>
  );
}

const s = StyleSheet.create({
  errScreen: { flex: 1, backgroundColor: colors.background, padding: 24 },
  errLogo: { color: colors.green, fontSize: 16, fontWeight: "900", letterSpacing: 2 },
  errTitle: { color: colors.text, fontSize: 26, fontWeight: "900", marginTop: 18 },
  errSub: { color: colors.muted, fontSize: 14, lineHeight: 21, marginTop: 8, marginBottom: 14 },
  errBox: { flex: 1, backgroundColor: colors.panel, borderColor: colors.border, borderWidth: 1, borderRadius: 12, padding: 14 },
  errText: { color: colors.amber, fontSize: 12, fontFamily: "monospace", lineHeight: 18 }
});
