import { Stack } from "expo-router";
import * as Notifications from "expo-notifications";
import Constants from "expo-constants";
import { Platform } from "react-native";
import { useEffect } from "react";
import { api } from "../src/api";

export default function RootLayout(){
  useEffect(()=>{
    let mounted=true;

    async function registerForPushNotifications(){
      try{
        if(Platform.OS==="android"){
          await Notifications.setNotificationChannelAsync("tradeguard-alerts",{
            name:"TradeGuard Alerts",
            importance:Notifications.AndroidImportance.HIGH,
            sound:"default",
            vibrationPattern:[0,250,250,250],
          });
        }

        const permissions=await Notifications.getPermissionsAsync();
        let status=permissions.status;

        if(status!=="granted"){
          const requested=await Notifications.requestPermissionsAsync();
          status=requested.status;
        }

        if(status!=="granted" || !mounted) return;

        const projectId=Constants.expoConfig?.extra?.eas?.projectId;
        if(!projectId) return;

        const tokenResponse=await Notifications.getExpoPushTokenAsync({projectId});
        const token=tokenResponse.data;

        if(token && mounted){
          await api.savePushToken(token);
        }
      }catch(error){
        // Push registration must never prevent the trading UI from loading.
        console.log("TradeGuard push registration:",error);
      }
    }

    registerForPushNotifications();

    return ()=>{
      mounted=false;
    };
  },[]);

  return <Stack screenOptions={{headerShown:false}}/>;
}
