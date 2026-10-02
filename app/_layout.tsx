import { Stack } from "expo-router";
import * as Notifications from "expo-notifications";
import Constants from "expo-constants";
import { Platform } from "react-native";
import { useEffect } from "react";
import { api } from "../src/api";

Notifications.setNotificationHandler({
  handleNotification: async()=>({
    shouldShowBanner:true,
    shouldShowList:true,
    shouldPlaySound:true,
    shouldSetBadge:false,
  }),
});

export default function RootLayout(){
  useEffect(()=>{
    let mounted=true;
    let registered=false;

    async function registerForPushNotifications(){
      try{
        if(registered || !mounted) return;

        const authToken=await api.hasToken();
        if(!authToken) return;

        if(Platform.OS==="android"){
          await Notifications.setNotificationChannelAsync("tradeguard-alerts",{
            name:"TradeGuard Alerts",
            importance:Notifications.AndroidImportance.HIGH,
            sound:"default",
            vibrationPattern:[0,250,250,250],
            lockscreenVisibility:Notifications.AndroidNotificationVisibility.PUBLIC,
          });
        }

        const permissions=await Notifications.getPermissionsAsync();
        let status=permissions.status;

        if(status!=="granted"){
          const requested=await Notifications.requestPermissionsAsync();
          status=requested.status;
        }

        if(status!=="granted" || !mounted) return;

        const projectId =
          Constants.easConfig?.projectId ??
          Constants.expoConfig?.extra?.eas?.projectId;

        if(!projectId){
          console.log("TradeGuard push registration: missing EAS projectId");
          return;
        }

        const tokenResponse=await Notifications.getExpoPushTokenAsync({projectId});
        const token=tokenResponse.data;

        if(token && mounted){
          const result=await api.savePushToken(token);
          if(result?.ok){
            registered=true;
            console.log("TradeGuard push registration: registered");
          }else{
            console.log("TradeGuard push registration: backend rejected token",result);
          }
        }
      }catch(error){
        console.log("TradeGuard push registration:",error);
      }
    }

    registerForPushNotifications();
    const retry=setInterval(registerForPushNotifications,15000);

    return ()=>{
      mounted=false;
      clearInterval(retry);
    };
  },[]);

  return <Stack screenOptions={{headerShown:false}}/>;
}
