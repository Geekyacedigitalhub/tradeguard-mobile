import { Platform } from "react-native";

// Push registration is a no-op until a Firebase project (google-services.json)
// is configured. The previous implementation imported expo-notifications,
// whose native module can crash the app at startup on devices without
// Firebase configuration. When Firebase is available, restore the FCM/Expo
// push-token flow here (see git history for the original implementation).
export async function registerPushNotifications(): Promise<void> {
  if (Platform.OS === "web") return;
  console.log("TradeGuard push: disabled in this build (no Firebase configuration).");
}
