import {useEffect,useState} from "react";
import {ActivityIndicator,Alert,Pressable,ScrollView,StyleSheet,Text,View} from "react-native";
import {colors} from "../../src/theme";
import {Panel} from "../../src/components/Panel";
import {api} from "../../src/api";

export default function Settings(){
 const [broker,setBroker]=useState<any>(null); const [health,setHealth]=useState<any>(null); const [account,setAccount]=useState<any>(null); const [switching,setSwitching]=useState(false);
 useEffect(()=>{const load=()=>{api.me().then(r=>setAccount(r.user)).catch(()=>setAccount(null));api.broker().then(setBroker).catch(()=>setBroker({connected:false,environment:"paper"}));api.brokerHealth().then(setHealth).catch(()=>setHealth(null))};load();const t=setInterval(load,5000);return()=>clearInterval(t)},[]);
 return <ScrollView style={s.screen} contentContainerStyle={s.c}>
  <Text style={s.title}>Settings</Text>
  <Panel><Text style={s.h}>Account</Text><Text style={s.l}>Email</Text><Text style={s.v}>{account?.email ?? "Loading..."}</Text><Text style={s.l}>Authentication</Text><Text style={s.v}>Signed in · secure session</Text><Text style={s.l}>2FA</Text><Text style={s.v}>Enabled</Text></Panel>
  <Panel><Text style={s.h}>Broker Connection</Text>
   {broker===null?<ActivityIndicator color={colors.green}/>:<><View style={s.statusRow}><View style={[s.dot,{backgroundColor:broker.connected?colors.green:"#f59e0b"}]}/><Text style={s.status}>{broker.connected?"CONNECTED":"NOT CONNECTED"}</Text></View>
   <Text style={s.l}>Bridge status</Text><Text style={s.v}>{health?.status?health.status.toUpperCase():"UNKNOWN"}</Text><Text style={s.l}>Last seen</Text><Text style={s.v}>{health?.last_seen?new Date(health.last_seen).toLocaleString():"Never"}</Text><Text style={s.l}>Environment</Text><Text style={s.v}>{broker.environment==="live"?"Live":"Paper / Demo"}</Text><View style={s.switchRow}><Pressable disabled={switching} onPress={()=>switchAccount("demo")} style={[s.modeButton,broker.environment!=="live"&&s.active]}><Text style={s.modeText}>DEMO</Text></Pressable><Pressable disabled={switching} onPress={()=>switchAccount("live")} style={[s.modeButton,broker.environment==="live"&&s.liveActive]}><Text style={s.modeText}>LIVE</Text></Pressable></View>{switching&&<ActivityIndicator color={colors.green}/>}
   <Text style={s.l}>Provider</Text><Text style={s.v}>{broker.provider==="none"?"No live broker":"MT5"}</Text>
   <Text style={s.note}>{broker.connected?"Broker connection is active.":"The app is currently using paper trading. Live broker credentials are not stored on the phone."}</Text></>}
  </Panel>
  <Panel><Text style={s.h}>Notifications</Text><Text style={s.v}>Push notifications enabled</Text><Text style={s.v}>Trade approvals required in Semi-Auto</Text></Panel>
 </ScrollView>
}
const s=StyleSheet.create({screen:{flex:1,backgroundColor:colors.background},c:{padding:18,paddingTop:58,gap:14,paddingBottom:30},title:{color:colors.text,fontSize:28,fontWeight:"900"},h:{color:colors.text,fontWeight:"900",fontSize:15,marginBottom:10},l:{color:colors.muted,fontSize:11,marginTop:7},v:{color:colors.text,fontSize:13,fontWeight:"700",marginTop:2},statusRow:{flexDirection:"row",alignItems:"center",gap:8},dot:{width:8,height:8,borderRadius:8},status:{color:colors.text,fontSize:12,fontWeight:"900"},switchRow:{flexDirection:"row",gap:10,marginTop:16},modeButton:{flex:1,borderWidth:1,borderColor:colors.border,borderRadius:10,padding:13,alignItems:"center"},active:{backgroundColor:colors.green,borderColor:colors.green},liveActive:{backgroundColor:"#b91c1c",borderColor:"#b91c1c"},modeText:{color:colors.text,fontWeight:"900",fontSize:12},note:{color:colors.muted,fontSize:11,lineHeight:17,marginTop:12}});
