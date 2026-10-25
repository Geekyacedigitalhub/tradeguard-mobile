import Constants, { ExecutionEnvironment } from "expo-constants";
import * as Notifications from "expo-notifications";
import { Platform } from "react-native";
import { api } from "./api";

export const ALERT_CHANNEL_ID = "tradeguard-alerts";

export type PushRegistrationOutcome =
  | { status: "registered"; token: string }
  | {
      status: "skipped";
      reason: "web" | "expo-go" | "no-session" | "no-project-id" | "permission-denied";
    }
  | { status: "failed"; error: unknown };

/**
 * Show TradeGuard alerts while the app is in the foreground. The handler must
 * be installed before the first notification arrives, so this runs at module
 * scope from the root layout.
 */
export function configureNotificationHandler(): void {
  if (Platform.OS === "web") return;
  Notifications.setNotificationHandler({
    handleNotification: async () => ({
      shouldShowBanner: true,
      shouldShowList: true,
      shouldPlaySound: true,
      shouldSetBadge: false,
    }),
  });
}

async function ensureAndroidAlertChannel(): Promise<void> {
  if (Platform.OS !== "android") return;
  await Notifications.setNotificationChannelAsync(ALERT_CHANNEL_ID, {
    name: "TradeGuard Alerts",
    importance: Notifications.AndroidImportance.HIGH,
    sound: "default",
    vibrationPattern: [0, 250, 250, 250],
    lockscreenVisibility: Notifications.AndroidNotificationVisibility.PUBLIC,
  });
}

/**
 * Register this device for push alerts.
 *
 * Expo Go cannot receive remote push notifications on SDK 53+, and Expo
 * requires the EAS project ID when requesting a token, so both cases are
 * reported as a skipped outcome instead of throwing.
 */
export async function registerPushNotifications(): Promise<PushRegistrationOutcome> {
  if (Platform.OS === "web") return { status: "skipped", reason: "web" };

  // Expo Go does not support remote push notifications on SDK 53+.
  if (Constants.executionEnvironment === ExecutionEnvironment.StoreClient) {
    return { status: "skipped", reason: "expo-go" };
  }

  const session = await api.hasToken();
  if (!session) return { status: "skipped", reason: "no-session" };

  await ensureAndroidAlertChannel();

  const current = await Notifications.getPermissionsAsync();
  let permission = current.status;
  if (permission !== "granted") {
    const requested = await Notifications.requestPermissionsAsync();
    permission = requested.status;
  }
  if (permission !== "granted") return { status: "skipped", reason: "permission-denied" };

  const projectId =
    Constants.easConfig?.projectId ?? Constants.expoConfig?.extra?.eas?.projectId;
  if (!projectId) return { status: "skipped", reason: "no-project-id" };

  try {
    const token = (await Notifications.getExpoPushTokenAsync({ projectId })).data;
    if (!token) return { status: "failed", error: new Error("Expo returned an empty push token") };
    const saved = await api.savePushToken(token);
    if (saved?.ok) return { status: "registered", token };
    return {
      status: "failed",
      error: new Error(saved?.message || "The TradeGuard backend rejected the push token."),
    };
  } catch (error) {
    return { status: "failed", error };
  }
}
