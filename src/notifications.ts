import * as Notifications from "expo-notifications";
import { Platform } from "react-native";
import { api } from "./api";

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: true,
    shouldSetBadge: false
  })
});

export async function registerPushNotifications() {
  if (Platform.OS === "web") return;
  const permissions = await Notifications.getPermissionsAsync();
  let status = permissions.status;
  if (status !== "granted") {
    const requested = await Notifications.requestPermissionsAsync();
    status = requested.status;
  }
  if (status !== "granted") return;
  const token = (await Notifications.getExpoPushTokenAsync()).data;
  await api.savePushToken(token);
}
