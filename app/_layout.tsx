import { Stack } from "expo-router";

// NOTE: push notifications (expo-notifications) are intentionally NOT loaded
// in this build. The native module requires a Firebase project
// (google-services.json); without it, touching the module on-device can crash
// the app at startup. Push support is re-enabled when a Firebase project is
// configured (see README → cTrader configuration / install notes).

export default function RootLayout(){
  return <Stack screenOptions={{headerShown:false}}/>;
}
