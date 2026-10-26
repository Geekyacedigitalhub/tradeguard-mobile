import { Platform } from "react-native";
import * as SecureStore from "expo-secure-store";

// expo-secure-store is a no-op stub on web, so web falls back to localStorage.
// Native keeps the platform secure store.
const WEB_KEY = "tradeguard_token";

function webStorage(): Storage | null {
  try {
    return (globalThis as any).localStorage ?? null;
  } catch {
    return null;
  }
}

export const tokenStorage = {
  async getItem(): Promise<string | null> {
    if (Platform.OS === "web") return webStorage()?.getItem(WEB_KEY) ?? null;
    return SecureStore.getItemAsync(WEB_KEY);
  },
  async setItem(value: string): Promise<void> {
    if (Platform.OS === "web") {
      webStorage()?.setItem(WEB_KEY, value);
      return;
    }
    return SecureStore.setItemAsync(WEB_KEY, value);
  },
  async removeItem(): Promise<void> {
    if (Platform.OS === "web") {
      webStorage()?.removeItem(WEB_KEY);
      return;
    }
    return SecureStore.deleteItemAsync(WEB_KEY);
  }
};
