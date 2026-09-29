import { Redirect } from "expo-router";
import { useEffect, useState } from "react";
import { ActivityIndicator, View } from "react-native";
import { api } from "../src/api";

export default function Index() {
  const [ready,setReady]=useState(false);
  const [signedIn,setSignedIn]=useState(false);
  useEffect(()=>{api.hasToken().then(v=>{setSignedIn(!!v);setReady(true);});},[]);
  if(!ready) return <View style={{flex:1,alignItems:"center",justifyContent:"center",backgroundColor:"#06120c"}}><ActivityIndicator color="#22c55e"/></View>;
  return signedIn ? <Redirect href="/(tabs)" /> : <Redirect href="/auth" />;
}
