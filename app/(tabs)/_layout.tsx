import {Tabs} from "expo-router";
import {Ionicons} from "@expo/vector-icons";
import {colors} from "../../src/theme";

const icons:any={
  index:"grid",
  markets:"pulse",
  strategy:"analytics",
  trades:"swap-horizontal",
  notifications:"notifications",
  bot:"hardware-chip",
  settings:"settings"
};

export default function TabLayout(){
  return <Tabs screenOptions={({route})=>({
    headerShown:false,
    tabBarStyle:{
      position:"absolute",
      backgroundColor:colors.surface,
      borderTopColor:colors.border,
      borderTopWidth:1,
      height:82,
      paddingHorizontal:6,
      paddingBottom:11,
      paddingTop:8
    },
    tabBarItemStyle:{borderRadius:12,marginHorizontal:2,marginVertical:5},
    tabBarActiveBackgroundColor:colors.surface2,
    tabBarHideOnKeyboard:true,
    tabBarActiveTintColor:colors.green,
    tabBarInactiveTintColor:colors.muted2,
    tabBarLabelStyle:{fontSize:9,fontWeight:"900",letterSpacing:.4},
    tabBarIcon:({color,size,focused})=>
      <Ionicons name={icons[route.name]??"ellipse"} size={focused?23:size} color={color}/>
  })}>
    <Tabs.Screen name="index" options={{title:"Command"}}/>
    <Tabs.Screen name="markets" options={{title:"Markets"}}/>
    <Tabs.Screen name="strategy" options={{title:"Intelligence"}}/>
    <Tabs.Screen name="trades" options={{title:"Positions"}}/>
    <Tabs.Screen name="notifications" options={{title:"Alerts"}}/>
    <Tabs.Screen name="bot" options={{title:"Autopilot"}}/>
    <Tabs.Screen name="settings" options={{title:"Settings"}}/>
  </Tabs>;
}
