import {useEffect,useState} from "react";
import {ActivityIndicator,Alert,Pressable,ScrollView,StyleSheet,Text,View} from "react-native";
import {router} from "expo-router";
import {colors} from "../../src/theme";
import {Panel} from "../../src/components/Panel";
import {api} from "../../src/api";

export default function Settings(){
 const [broker,setBroker]=useState<any>(null);
 const [health,setHealth]=useState<any>(null);
 const [account,setAccount]=useState<any>(null);
 const [switching,setSwitching]=useState(false);
 const [connecting,setConnecting]=useState(false);

 const load=async()=>{
  const results=await Promise.allSettled([api.me(),api.broker(),api.brokerHealth()]);
  const me=results[0]; const b=results[1]; const h=results[2];
  if(me.status==="fulfilled") setAccount(me.value.user); else setAccount(null);
  if(b.status==="fulfilled") setBroker(b.value); else setBroker({connected:false,environment:"paper",provider:"none"});
  if(h.status==="fulfilled") setHealth(h.value); else setHealth(null);
 };

 useEffect(()=>{load();const t=setInterval(load,5000);return()=>clearInterval(t)},[]);

 async function connectMT5(){
  setConnecting(true);
  try{
   const h=await api.brokerHealth();
   setHealth(h);
   const b=await api.broker();
   setBroker(b);
   if(b?.connected) Alert.alert("MT5 Connected","The MT5 bridge is connected and the account is available.");
   else Alert.alert("MT5 Not Connected","Open MetaTrader 5 and run the TradeGuard MT5 Bridge on your Windows PC, then tap CONNECT MT5 again.");
  }catch(e:any){
   Alert.alert("Connection check failed",e?.message||"Could not check the MT5 bridge.");
  }finally{setConnecting(false);}
 }

 async function switchAccount(profile:"demo"|"live"){
  if(profile==="live"){
   Alert.alert("Live trading","Live trading is protected. The live account switch requires an explicit confirmation and a connected MT5 bridge.",[
    {text:"Cancel",style:"cancel"},
    {text:"Continue",style:"destructive",onPress:()=>doSwitch("live","LIVE_TRADING")}
   ]);
   return;
  }
  await doSwitch("demo");
 }

 async function doSwitch(profile:"demo"|"live",confirmation?:string){
  setSwitching(true);
  try{
   await api.switchBrokerAccount(profile,confirmation);
   Alert.alert("Account switch queued",profile==="live"?"Live account switch was queued.":"Demo account switch was queued.");
   await load();
  }catch(e:any){Alert.alert("Account switch",e?.message||"Could not switch the MT5 account.");}
  finally{setSwitching(false);}
 }

 function signOut(){
  Alert.alert("Sign out","Sign out of this TradeGuard account?",[
   {text:"Cancel",style:"cancel"},
   {text:"Sign out",style:"destructive",onPress:async()=>{await api.clearToken();router.replace("/auth");}}
  ]);
 }

 return <ScrollView style={s.screen} contentContainerStyle={s.c}>
  <Text style={s.title}>Settings</Text>

  <Panel>
   <Text style={s.h}>Account</Text>
   <Text style={s.l}>Email</Text><Text style={s.v}>{account?.email ?? "Loading..."}</Text>
   <Text style={s.l}>Authentication</Text><Text style={s.v}>Signed in · secure session</Text>
   <Text style={s.l}>2FA</Text><Text style={s.v}>Enabled</Text>
   <Pressable onPress={signOut} style={s.signOut}><Text style={s.signOutText}>SIGN OUT</Text></Pressable>
  </Panel>

  <Panel>
   <Text style={s.h}>Broker Connection</Text>
   {broker===null?<ActivityIndicator color={colors.green}/>:<>
    <View style={s.statusRow}><View style={[s.dot,{backgroundColor:broker.connected?colors.green:"#f59e0b"}]}/><Text style={s.status}>{broker.connected?"CONNECTED":"NOT CONNECTED"}</Text></View>
    <Text style={s.l}>Bridge status</Text><Text style={s.v}>{health?.status?health.status.toUpperCase():"UNKNOWN"}</Text>
    <Text style={s.l}>Last seen</Text><Text style={s.v}>{health?.last_seen?new Date(health.last_seen).toLocaleString():"Never"}</Text>
    <Text style={s.l}>Environment</Text><Text style={s.v}>{broker.environment==="live"?"Live":"Paper / Demo"}</Text>
    <Pressable disabled={connecting} onPress={connectMT5} style={s.connectButton}>
     {connecting?<ActivityIndicator color="#021008"/>:<Text style={s.connectText}>{broker.connected?"REFRESH MT5 CONNECTION":"CONNECT MT5"}</Text>}
    </Pressable>
    <View style={s.switchRow}>
     <Pressable disabled={switching} onPress={()=>switchAccount("demo")} style={[s.modeButton,broker.environment!=="live"&&s.active]}><Text style={s.modeText}>DEMO</Text></Pressable>
     <Pressable disabled={switching} onPress={()=>switchAccount("live")} style={[s.modeButton,broker.environment==="live"&&s.liveActive]}><Text style={s.modeText}>LIVE</Text></Pressable>
    </View>
    {switching&&<ActivityIndicator color={colors.green}/>}
    <Text style={s.l}>Provider</Text><Text style={s.v}>{broker.provider==="none"?"No live broker":"MT5"}</Text>
    <Text style={s.note}>{broker.connected?"Broker connection is active.":"Connect through the MT5 bridge. Broker credentials stay off the phone."}</Text>
   </>}
  </Panel>

  <Panel><Text style={s.h}>Notifications</Text><Text style={s.v}>Push notifications enabled</Text><Text style={s.v}>Trade approvals required in Semi-Auto</Text></Panel>
 </ScrollView>
}

const s=StyleSheet.create({
 screen:{flex:1,backgroundColor:colors.background},
 c:{padding:18,paddingTop:58,gap:14,paddingBottom:30},
 title:{color:colors.text,fontSize:28,fontWeight:"900"},
 h:{color:colors.text,fontWeight:"900",fontSize:15,marginBottom:10},
 l:{color:colors.muted,fontSize:11,marginTop:7},
 v:{color:colors.text,fontSize:13,fontWeight:"700",marginTop:2},
 statusRow:{flexDirection:"row",alignItems:"center",gap:8},
 dot:{width:8,height:8,borderRadius:8},
 status:{color:colors.text,fontSize:12,fontWeight:"900"},
 connectButton:{backgroundColor:colors.green,borderRadius:10,padding:13,alignItems:"center",marginTop:16},
 connectText:{color:"#021008",fontWeight:"900",fontSize:12},
 switchRow:{flexDirection:"row",gap:10,marginTop:12},
 modeButton:{flex:1,borderWidth:1,borderColor:colors.border,borderRadius:10,padding:13,alignItems:"center"},
 active:{backgroundColor:colors.green,borderColor:colors.green},
 liveActive:{backgroundColor:"#b91c1c",borderColor:"#b91c1c"},
 modeText:{color:colors.text,fontWeight:"900",fontSize:12},
 note:{color:colors.muted,fontSize:11,lineHeight:17,marginTop:12},
 signOut:{marginTop:16,borderWidth:1,borderColor:"#7f1d1d",borderRadius:10,padding:12,alignItems:"center"},
 signOutText:{color:"#fca5a5",fontWeight:"900",fontSize:12}
});
