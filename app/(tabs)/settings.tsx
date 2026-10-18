import {useEffect,useState} from "react";
import {ActivityIndicator,Alert,AppState,Linking,Pressable,ScrollView,StyleSheet,Text,View} from "react-native";
import {router} from "expo-router";
import {colors,radii,shadows} from "../../src/theme";
import {Panel} from "../../src/components/Panel";
import {api} from "../../src/api";
import {emitCTraderAccountChanged} from "../../src/ctraderAccountEvents";

export default function Settings(){
 const [account,setAccount]=useState<any>(null);
 const [ctrader,setCtrader]=useState<any>(null);
 const [ctraderAccounts,setCtraderAccounts]=useState<any[]>([]);
 const [ctraderBusy,setCtraderBusy]=useState(false);

 const load=async()=>{
  const results=await Promise.allSettled([api.me(),api.ctraderStatus()]);
  const me=results[0]; const ct=results[1];
  if(me.status==="fulfilled") setAccount(me.value.user);
  if(ct.status==="fulfilled") setCtrader(ct.value);
  // Preserve the last known account status during temporary network failures.
 };

 useEffect(()=>{
  let active=AppState.currentState==="active";
  let loading=false;
  const refresh=()=>{
   if(!active||loading)return;
   loading=true;
   void load().finally(()=>{loading=false});
  };
  refresh();
  const timer=setInterval(refresh,30000);
  const sub=AppState.addEventListener("change",state=>{
   active=state==="active";
   if(active)refresh();
  });
  return()=>{clearInterval(timer);sub.remove()};
 },[]);


 async function connectCTrader(){
  setCtraderBusy(true);
  try{
   const result=await api.ctraderOAuthStart();
   await Linking.openURL(result.authorization_url);
   Alert.alert("cTrader authorization","Approve TradeGuard in the browser. When the confirmation page appears, return to the app and press REFRESH cTRADER.");
  }catch(e:any){Alert.alert("cTrader setup",e?.message||"Could not start cTrader authorization.");}
  finally{setCtraderBusy(false);}
 }

 async function refreshCTraderAccounts(){
  setCtraderBusy(true);
  try{
   const status=await api.ctraderStatus();
   setCtrader(status);
   if(!status.authorized){Alert.alert("cTrader","Authorize the cTrader account first.");return;}
   const result=await api.ctraderAccounts();
   setCtraderAccounts(result.accounts||[]);
   if(!result.accounts?.length) Alert.alert("cTrader","No trading accounts were returned for this authorization.");
  }catch(e:any){Alert.alert("cTrader connection",e?.message||"Could not load cTrader accounts.");}
  finally{setCtraderBusy(false);}
 }

 async function selectCTraderAccount(accountId:number){
  setCtraderBusy(true);
  try{
   const result=await api.ctraderSelectAccount(accountId);
   const selectedEnvironment=String(result?.environment??"").trim().toLowerCase();
   setCtrader((prev:any)=>({...prev,authorized:true,account_id:result.account_id,environment:result.environment??null}));
   emitCTraderAccountChanged({account_id:result.account_id,environment:result.environment??null});
   if(selectedEnvironment.includes("demo")){
    Alert.alert("cTrader demo connected","The selected account is reported as demo. Automated orders remain locked while execution safety checks are completed.");
   }else{
    Alert.alert("Account environment unverified","The server did not confirm this account as demo. TradeGuard keeps automated execution locked; refresh cTrader status and verify the selected account.");
   }
  }catch(e:any){Alert.alert("cTrader account",e?.message||"Could not select this account.");}
  finally{setCtraderBusy(false);}
 }

 function signOut(){
  Alert.alert("Sign out","Sign out of this TradeGuard account?",[
   {text:"Cancel",style:"cancel"},
   {text:"Sign out",style:"destructive",onPress:async()=>{await api.clearToken();router.replace("/auth");}}
  ]);
 }

 return <ScrollView style={s.screen} contentContainerStyle={s.c}>
  <View style={s.header}><View style={{flex:1}}><Text style={s.eyebrow}>TRADEGUARD / SYSTEM CONTROL</Text><Text style={s.title}>System & Broker</Text><Text style={s.sub}>Account security and cTrader cloud connectivity.</Text></View><View style={[s.healthChip,{borderColor:ctrader?.account_id?colors.borderGlow:colors.border}]}><View style={[s.healthDot,{backgroundColor:ctrader?.account_id?colors.green:colors.red}]}/><Text style={[s.healthText,{color:ctrader?.account_id?colors.green:colors.red}]}>{ctrader?.account_id?"CONNECTED":"OFFLINE"}</Text></View></View>
  <View style={s.terminalBar}><View style={s.terminalStatus}><View style={[s.terminalDot,{backgroundColor:String(ctrader?.environment??"").toLowerCase().includes("demo")?colors.green:colors.amber}]}/><Text style={s.terminalText}>CTRADER CLOUD</Text></View><View style={s.terminalDivider}/><Text style={s.terminalLock}>{String(ctrader?.environment??"").toLowerCase().includes("live")?"LIVE ACCOUNT · EXECUTION LOCKED":String(ctrader?.environment??"").toLowerCase().includes("demo")?"DEMO ACCOUNT · SAFETY LOCK ACTIVE":"ENVIRONMENT UNVERIFIED · EXECUTION LOCKED"}</Text></View>

  <Panel><View style={s.panelHead}><View><Text style={s.label}>IDENTITY</Text><Text style={s.h}>Account</Text></View><Text style={s.secure}>SECURE</Text></View>
   <Text style={s.l}>Email</Text><Text style={s.v}>{account?.email ?? "Loading..."}</Text>
   <Text style={s.l}>Authentication</Text><Text style={s.v}>Signed in · secure session</Text>
   <Text style={s.l}>Two-factor authentication</Text><Text style={s.v}>Not verified by TradeGuard</Text>
   <Pressable onPress={signOut} style={s.signOut}><Text style={s.signOutText}>SIGN OUT</Text></Pressable>
  </Panel>

  <Panel><View style={s.panelHead}><View><Text style={s.label}>CLOUD EXECUTION</Text><Text style={s.h}>cTrader Demo</Text></View><View style={s.securePill}><Text style={s.securePillText}>{ctrader?.account_id?"CONNECTED":"NOT CONNECTED"}</Text></View></View>
   <Text style={s.note}>cTrader is cloud-connected, so your PC does not need to stay on. Automated order execution remains locked until safety checks pass.</Text>
   <Text style={s.l}>Authorization</Text><Text style={s.v}>{ctrader?.authorized?"Authorized":"Not authorized"}</Text>
   {ctrader?.account_id&&<><Text style={s.l}>Account ID</Text><Text style={s.v}>{ctrader.account_id}</Text><Text style={s.l}>Environment</Text><Text style={s.v}>{String(ctrader.environment??"UNKNOWN").toUpperCase()}</Text></>}
   <Pressable disabled={ctraderBusy} onPress={ctrader?.authorized?refreshCTraderAccounts:connectCTrader} style={s.connectButton}>
    {ctraderBusy?<ActivityIndicator color="#021008"/>:<Text style={s.connectText}>{ctrader?.authorized?"REFRESH cTRADER":"CONNECT cTRADER DEMO"}</Text>}
   </Pressable>
   {ctraderAccounts.map((item:any)=><Pressable key={String(item.account_id)} disabled={ctraderBusy||!!item.is_live} onPress={()=>{if(item.is_live){Alert.alert("Live account unavailable","TradeGuard is in demo-only mode. Select a cTrader demo account instead.");return;}void selectCTraderAccount(Number(item.account_id));}} style={[s.accountChoice,(ctraderBusy||item.is_live)&&{opacity:0.5}]}>
    <Text style={s.accountChoiceTitle}>{item.account_id}</Text><Text style={s.accountChoiceMeta}>{item.is_live?"LIVE · UNAVAILABLE IN DEMO PHASE":"DEMO"} · Login {item.trader_login||"—"}</Text>
   </Pressable>)}
  </Panel>

  <Panel><View style={s.panelHead}><View><Text style={s.label}>ALERT DELIVERY</Text><Text style={s.h}>Notifications</Text></View><Text style={s.secure}>READY</Text></View><Text style={s.v}>Push notifications enabled</Text><Text style={s.v}>Trade approvals required in Semi-Auto</Text></Panel>
 </ScrollView>
}

const s=StyleSheet.create({
 screen:{flex:1,backgroundColor:colors.background},
 c:{padding:18,paddingTop:58,gap:14,paddingBottom:112},
 header:{flexDirection:"row",justifyContent:"space-between",alignItems:"flex-start",gap:10},
 terminalBar:{flexDirection:"row",alignItems:"center",gap:9,paddingHorizontal:12,paddingVertical:10,borderRadius:11,backgroundColor:colors.surface2,borderWidth:1,borderColor:colors.border},terminalStatus:{flexDirection:"row",alignItems:"center",gap:6},terminalDot:{width:6,height:6,borderRadius:6,backgroundColor:colors.green},terminalText:{color:colors.green,fontSize:8,fontWeight:"900",letterSpacing:.8},terminalDivider:{width:1,height:15,backgroundColor:colors.border},terminalLock:{color:colors.muted,fontSize:7,fontWeight:"900",letterSpacing:.5,flexShrink:1},
 eyebrow:{color:colors.green,fontSize:8,fontWeight:"900",letterSpacing:1.5},
 title:{color:colors.text,fontSize:28,fontWeight:"900",marginTop:3},
 sub:{color:colors.muted,fontSize:10,lineHeight:15,marginTop:4},
 healthChip:{flexDirection:"row",alignItems:"center",gap:5,paddingHorizontal:9,paddingVertical:7,borderRadius:radii.pill,borderWidth:1,backgroundColor:colors.surface2},
 healthDot:{width:6,height:6,borderRadius:6},healthText:{fontSize:7,fontWeight:"900",letterSpacing:.8},
 panelHead:{flexDirection:"row",justifyContent:"space-between",alignItems:"center",marginBottom:10},
 label:{color:colors.muted,fontSize:8,fontWeight:"900",letterSpacing:1.1},
 secure:{color:colors.green,fontSize:7,fontWeight:"900",letterSpacing:1},
 securePill:{paddingHorizontal:7,paddingVertical:5,borderRadius:radii.pill,backgroundColor:colors.surface2,borderWidth:1,borderColor:colors.borderGlow},
 securePillText:{color:colors.green,fontSize:6,fontWeight:"900",letterSpacing:.7},

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
 keyBox:{marginTop:12,padding:12,borderRadius:10,borderWidth:1,borderColor:colors.borderGlow,backgroundColor:colors.surface2},
 keyText:{color:colors.text,fontSize:11,fontWeight:"700"},
 keyHint:{color:colors.muted,fontSize:9,marginTop:7},
 accountChoice:{marginTop:9,padding:12,borderRadius:10,borderWidth:1,borderColor:colors.border,backgroundColor:colors.surface2},
 accountChoiceTitle:{color:colors.text,fontWeight:"900",fontSize:12},
 accountChoiceMeta:{color:colors.muted,fontSize:9,marginTop:4},
 signOut:{marginTop:16,borderWidth:1,borderColor:"#7f1d1d",borderRadius:10,padding:12,alignItems:"center"},
 signOutText:{color:"#fca5a5",fontWeight:"900",fontSize:12}
});
