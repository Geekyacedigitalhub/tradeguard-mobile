import {Tabs} from "expo-router";
import {Ionicons} from "@expo/vector-icons";
import {colors} from "../../src/theme";

const icons:any={
  index:"grid-outline",
  markets:"stats-chart-outline",
  strategy:"analytics-outline",
  trades:"swap-vertical-outline",
  notifications:"notifications-outline",
  bot:"hardware-chip-outline",
  settings:"settings-outline"
};

export default function TabLayout(){
  return <Tabs screenOptions={({route})=>({
    headerShown:false,
    tabBarStyle:{
      backgroundColor:colors.surface,
      borderTopColor:colors.border,
      borderTopWidth:1,
      height:78,
      paddingBottom:10,
      paddingTop:8
    },
    tabBarActiveTintColor:colors.green,
    tabBarInactiveTintColor:"#64796e",
    tabBarLabelStyle:{fontSize:10,fontWeight:"800",letterSpacing:0.2},
    tabBarIcon:({color,size,focused})=>
      <Ionicons name={icons[route.name]??"ellipse-outline"} size={focused?23:size} color={color}/>
  })}>
    <Tabs.Screen name="index" options={{title:"Home"}}/>
    <Tabs.Screen name="markets" options={{title:"Markets"}}/>
    <Tabs.Screen name="strategy" options={{title:"Strategy"}}/>
    <Tabs.Screen name="trades" options={{title:"Trades"}}/>
    <Tabs.Screen name="notifications" options={{title:"Alerts"}}/>
    <Tabs.Screen name="bot" options={{title:"Bot"}}/>
    <Tabs.Screen name="settings" options={{title:"Settings"}}/>
  </Tabs>;
}