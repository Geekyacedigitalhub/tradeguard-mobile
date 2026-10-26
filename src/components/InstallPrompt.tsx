import {Platform, Pressable, StyleSheet, Text, View} from "react-native";
import {Ionicons} from "@expo/vector-icons";
import {useEffect, useState} from "react";
import {colors} from "../theme";

type BeforeInstallPromptEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{outcome: "accepted" | "dismissed"}>;
};

// On Android/Chrome, offer the native PWA install. On iOS Safari the event
// never fires, so this stays hidden and users use Share → Add to Home Screen.
export function InstallPrompt() {
  const [deferred, setDeferred] = useState<BeforeInstallPromptEvent | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [installing, setInstalling] = useState(false);

  useEffect(() => {
    if (Platform.OS !== "web") return;
    const win = window as Window & {navigator?: {standalone?: boolean}};
    if (win.navigator?.standalone) return;
    const onPrompt = (e: Event) => {
      e.preventDefault();
      setDeferred(e as BeforeInstallPromptEvent);
    };
    const onInstalled = () => setDeferred(null);
    win.addEventListener("beforeinstallprompt", onPrompt);
    win.addEventListener("appinstalled", onInstalled);
    return () => {
      win.removeEventListener("beforeinstallprompt", onPrompt);
      win.removeEventListener("appinstalled", onInstalled);
    };
  }, []);

  if (Platform.OS !== "web" || dismissed || !deferred) return null;

  return (
    <View style={s.wrap}>
      <View style={s.icon}>
        <Ionicons name="phone-portrait-outline" size={17} color={colors.green} />
      </View>
      <View style={{flex: 1}}>
        <Text style={s.title}>Install TradeGuard</Text>
        <Text style={s.sub}>Full-screen app experience · works offline · home-screen shortcut</Text>
      </View>
      <Pressable
        disabled={installing}
        style={[s.button, installing && {opacity: 0.6}]}
        onPress={async () => {
          setInstalling(true);
          try {
            await deferred.prompt();
            const choice = await deferred.userChoice;
            if (choice.outcome === "accepted") setDeferred(null);
          } finally {
            setInstalling(false);
          }
        }}
      >
        <Ionicons name="download-outline" size={13} color="#021008" />
        <Text style={s.buttonText}>{installing ? "INSTALLING…" : "INSTALL"}</Text>
      </Pressable>
      <Pressable hitSlop={8} onPress={() => setDismissed(true)} style={s.close}>
        <Ionicons name="close" size={14} color={colors.muted} />
      </Pressable>
    </View>
  );
}

const s = StyleSheet.create({
  wrap: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    borderRadius: 13,
    borderWidth: 1,
    borderColor: colors.borderGlow,
    backgroundColor: colors.surface,
    padding: 12
  },
  icon: {
    width: 34,
    height: 34,
    borderRadius: 10,
    backgroundColor: "#08261a",
    borderWidth: 1,
    borderColor: colors.borderStrong,
    alignItems: "center",
    justifyContent: "center"
  },
  title: {color: colors.text, fontSize: 12, fontWeight: "900"},
  sub: {color: colors.muted, fontSize: 9, marginTop: 3},
  button: {
    flexDirection: "row",
    alignItems: "center",
    gap: 5,
    backgroundColor: colors.green,
    borderRadius: 9,
    paddingVertical: 9,
    paddingHorizontal: 11
  },
  buttonText: {color: "#021008", fontSize: 8, fontWeight: "900", letterSpacing: 0.5},
  close: {padding: 4}
});
