import { Redirect } from "expo-router";
import { useEffect, useState } from "react";
import { ActivityIndicator, View } from "react-native";
import { api, isUnauthorized } from "../src/api";

export default function Index() {
  const [ready,setReady]=useState(false);
  const [signedIn,setSignedIn]=useState(false);

  useEffect(()=>{
    let mounted=true;

    async function bootstrap(){
      const token=await api.hasToken();
      if(!token){
        if(mounted){setSignedIn(false);setReady(true);}
        return;
      }

      try{
        await api.me();
        if(mounted)setSignedIn(true);
      }catch(error){
        // Only an authentication failure should sign the user out. A timeout or
        // offline network must not discard a session that may still be valid.
        if(isUnauthorized(error)){
          await api.clearToken();
          if(mounted)setSignedIn(false);
        }else if(mounted){
          setSignedIn(true);
        }
      }finally{
        if(mounted)setReady(true);
      }
    }

    bootstrap();
    return ()=>{mounted=false};
  },[]);

  if(!ready) return <View style={{flex:1,alignItems:"center",justifyContent:"center",backgroundColor:"#06120c"}}><ActivityIndicator color="#22c55e"/></View>;
  return signedIn ? <Redirect href="/(tabs)" /> : <Redirect href="/auth" />;
}
