import { Redirect } from "expo-router";
import { useEffect, useState } from "react";
import { ActivityIndicator, View } from "react-native";
import { api } from "../src/api";
import { registerPushNotifications } from "../src/notifications";

export default function Index() {
  const [ready,setReady]=useState(false);
  const [signedIn,setSignedIn]=useState(false);

  useEffect(()=>{
    async function bootstrap(){
      const token=await api.hasToken();
      if(!token){
        setSignedIn(false);
        setReady(true);
        return;
      }

      try{
        await api.me();
        setSignedIn(true);
        try{await api.pairBroker("windows-mt5")}catch{}
        try{await registerPushNotifications()}catch{}
      }catch(error:any){
        const message=String(error?.message ?? "");
        if(message.includes("401") || message.toLowerCase().includes("user not found") || message.toLowerCase().includes("invalid or expired")){
          await api.clearToken();
          setSignedIn(false);
        }else{
          setSignedIn(true);
        }
      }finally{
        setReady(true);
      }
    }

    bootstrap();
  },[]);

  if(!ready) return <View style={{flex:1,alignItems:"center",justifyContent:"center",backgroundColor:"#06120c"}}><ActivityIndicator color="#22c55e"/></View>;
  return signedIn ? <Redirect href="/(tabs)" /> : <Redirect href="/auth" />;
}
