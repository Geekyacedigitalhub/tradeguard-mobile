// Pre-router crash gate.
//
// The root layout (and everything after it) lives inside the router, so if the
// router/first-render path is what kills the app, a diagnostic screen that
// renders inside it can never be seen. This module solves that: it runs from
// entry.ts BEFORE the router loads, and registers a plain react-native root
// (View/Text/ScrollView only — no expo modules, no screens, no SVG) that shows
// the crash journal from the previous session.
//
// It only activates when the previous session ended without a clean exit, so
// a healthy app never sees it.
import React from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { readPreviousSession } from "./crashjournal";

export type GateState =
  | { kind: "none" }
  | { kind: "crash"; lines: string[] };

// Decide whether the gate must render. Safe to call at module scope.
export function computeGate(): GateState {
  try {
    const prev = readPreviousSession();
    if (prev && !prev.clean) return { kind: "crash", lines: prev.lines };
    return { kind: "none" };
  } catch {
    return { kind: "none" };
  }
}

const C = {
  bg: "#06120c",
  panel: "#0b1f16",
  border: "#1d3a2c",
  green: "#22c55e",
  text: "#e8f5ee",
  muted: "#8aa596",
  amber: "#fbbf24"
};

export function GateScreen({
  lines,
  onContinue
}: {
  lines: string[];
  onContinue: () => void;
}) {
  const hadError = lines.some((l) => /js_error|render_error/.test(l));
  return (
    <View style={g.root}>
      <Text style={g.logo}>TRADEGUARD</Text>
      <Text style={g.title}>Last session ended unexpectedly</Text>
      <Text style={g.sub}>
        {hadError
          ? "The app recorded an error before it stopped. Screenshot this screen and send it to the developer — the log below shows exactly where it failed."
          : "The app stopped before it finished starting up. Screenshot this screen and send it to the developer — the log below shows exactly how far it got."}
      </Text>
      <Text style={g.label}>EVENT LOG (previous session)</Text>
      <ScrollView style={g.box} nestedScrollEnabled>
        <Text style={g.mono}>{lines.join("\n") || "(empty)"}</Text>
      </ScrollView>
      <Pressable style={g.btn} onPress={onContinue}>
        <Text style={g.btnText}>Open the app anyway</Text>
      </Pressable>
    </View>
  );
}

const g = StyleSheet.create({
  root: { flex: 1, backgroundColor: C.bg, padding: 18 },
  logo: { color: C.green, fontSize: 14, fontWeight: "900", letterSpacing: 2 },
  title: { color: C.text, fontSize: 21, fontWeight: "900", marginTop: 12 },
  sub: { color: C.muted, fontSize: 13, lineHeight: 19, marginTop: 8, marginBottom: 10 },
  label: { color: C.green, fontSize: 11, fontWeight: "900", letterSpacing: 1, marginTop: 8, marginBottom: 6 },
  box: { flex: 1, backgroundColor: C.panel, borderColor: C.border, borderWidth: 1, borderRadius: 12, padding: 12 },
  mono: { color: C.amber, fontSize: 11, fontFamily: "monospace", lineHeight: 16 },
  btn: { marginTop: 14, backgroundColor: C.green, borderRadius: 10, paddingVertical: 14, alignItems: "center" },
  btnText: { color: "#04140c", fontSize: 14, fontWeight: "900" }
});
