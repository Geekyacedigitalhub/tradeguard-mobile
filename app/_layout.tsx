import { Stack, router } from "expo-router";
import { useEffect } from "react";
import { AppState } from "react-native";
import { onAuthFailure } from "../src/api";
import {
  configureNotificationHandler,
  registerPushNotifications,
} from "../src/notifications";

// Install the foreground notification handler as soon as the app loads.
configureNotificationHandler();

export default function RootLayout(){
  // An expired or revoked session is detected by any API call. Send the user
  // back to sign-in instead of leaving tabs full of authorization errors.
  useEffect(()=>onAuthFailure(()=>{router.replace("/auth");}),[]);

  useEffect(()=>{
    let mounted=true;
    let registered=false;

    async function syncPushRegistration(){
      if(registered || !mounted) return;
      try{
        const outcome=await registerPushNotifications();
        if(!mounted) return;

        if(outcome.status==="registered"){
          registered=true;
          console.log("TradeGuard push registration: registered");
          return;
        }
        if(outcome.status==="failed"){
          console.log("TradeGuard push registration: failed",outcome.error);
          return;
        }
        // A missing session is the normal pre-login state; only surface the
        // configuration problems that need developer attention.
        if(outcome.reason!=="no-session"){
          console.log("TradeGuard push registration skipped:",outcome.reason);
        }
      }catch(error){
        console.log("TradeGuard push registration:",error);
      }
    }

    void syncPushRegistration();
    // Retry until the user signs in, then re-check permission changes and
    // token rotation while the app is running.
    const retry=setInterval(()=>{void syncPushRegistration();},60000);
    const appStateSubscription=AppState.addEventListener("change",state=>{
      if(state==="active") void syncPushRegistration();
    });

    return ()=>{
      mounted=false;
      clearInterval(retry);
      appStateSubscription.remove();
    };
  },[]);

  return <Stack screenOptions={{headerShown:false}}/>;
}
