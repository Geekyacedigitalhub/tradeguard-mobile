import { Redirect } from "expo-router";
import { useEffect, useState } from "react";
import { ActivityIndicator, View } from "react-native";
import { api } from "../src/api";
import { registerPushNotifications } from "../src/notifications";

export default function Index() {
  const [ready,setReady]=useState(false);
  const [signedIn,setSignedIn]=useState(false);
  useEffect(()=>{api.hasToken().then(async v=>{setSignedIn(!!v); if(v){try{await api.pairBroker("windows-mt5")}catch{} try{await registerPushNotifications()}catch{}} setReady(true);});},[]);
  if(!ready) return <View style={{flex:1,alignItems:"center",justifyContent:"center",backgroundColor:"#06120c"}}><ActivityIndicator color="#22c55e"/></View>;
  return signedIn ? <Redirect href="/(tabs)" /> : <Redirect href="/auth" />;
}
