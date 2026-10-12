import {useEffect,useState} from "react";
import {ActivityIndicator,Alert,Linking,Pressable,ScrollView,StyleSheet,Text,View,AppState} from "react-native";
import {router} from "expo-router";
import {colors,radii} from "../../src/theme";
import {Panel} from "../../src/components/Panel";
import {api} from "../../src/api";

export default function Settings(){
 const [account,setAccount]=useState<any>(null);
 const [health,setHealth]=useState<any>(null);
 const [ctrader,setCtrader]=useState<any>(null);
 const [ctraderAccounts,setCtraderAccounts]=useState<any[]>([]);
 const [ctraderBusy,setCtraderBusy]=useState(false);
 const [detail,setDetail]=useState<any>(null);
 const [loadError,setLoadError]=useState("");
 const [detailError,setDetailError]=useState("");

 const load=async()=>{
  const results=await Promise.allSettled([api.me(),api.ctraderStatus(),api.ctraderConnection(),api.ctraderAccount()]);
  const me=results[0],ct=results[1],conn=results[2],details=results[3];
  if(me.status==="fulfilled")setAccount(me.value.user);else setAccount(null);
  if(ct.status==="fulfilled")setCtrader(ct.value);else setCtrader({authorized:false});
  if(conn.status==="fulfilled")setHealth(conn.value);else setHealth(null);
  if(details.status==="fulfilled"){
   setDetail(details.value);
   setDetailError("");
  }else{
   // Keep the last confirmed broker snapshot visible during a transient outage.
   // The warning below makes clear that retained values may be stale.
   setDetailError(String(details.reason?.message??"Broker account refresh failed"));
  }
  setLoadError(ct.status==="rejected"?String(ct.reason?.message??"Unable to contact cTrader service"):"");
 };

 useEffect(()=>{
  load();
  const timer=setInterval(load,20000);
  const sub=AppState.addEventListener("change",state=>{if(state==="active")load()});
  return()=>{clearInterval(timer);sub.remove()};
 },[]);

 async function connectCTrader(){
  setCtraderBusy(true);
  try{
   const result=await api.ctraderOAuthStart();
   await Linking.openURL(result.authorization_url);
  }catch(e:any){Alert.alert("cTrader setup",e?.message||"Could not start cTrader authorization.");}
  finally{setCtraderBusy(false);}
 }

 async function refreshCTraderAccounts(){
  setCtraderBusy(true);
  try{
   const status=await api.ctraderStatus();
   setCtrader(status);
   if(!status.authorized){Alert.alert("cTrader","Authorize cTrader first.");return;}
   const result=await api.ctraderAccounts();
   const list=Array.isArray(result.accounts)?result.accounts:[];
   setCtraderAccounts(list);
   if(!list.length)Alert.alert("cTrader","No trading accounts were returned for this authorization.");
  }catch(e:any){Alert.alert("cTrader connection",e?.message||"Could not load cTrader accounts.");}
  finally{setCtraderBusy(false);}
 }

 async function selectCTraderAccount(accountId:number){
  setCtraderBusy(true);
  try{
   const result=await api.ctraderSelectAccount(accountId);
   setCtrader((prev:any)=>({...prev,authorized:true,account_id:result.account_id,environment:result.environment}));
   const details=await api.ctraderAccount();
   setDetail(details);
   Alert.alert("cTrader account selected",result.environment==="demo"?"Demo account selected. Automated execution remains Demo-only.":"Live account selected for account visibility. Automated Live orders remain disabled.");
  }catch(e:any){Alert.alert("cTrader account",e?.message||"Could not select this account.");}
  finally{setCtraderBusy(false);}
 }

 function signOut(){
  Alert.alert("Sign out","Sign out of TradeGuard?",[
   {text:"Cancel",style:"cancel"},
   {text:"Sign out",style:"destructive",onPress:async()=>{await api.clearToken();router.replace("/auth");}}
  ]);
 }

 const isLive=ctrader?.environment==="live";
 // A saved account selection is not a live broker heartbeat. Use the
 // latest successful cTrader account snapshot for the online indicator.
 const connected=!!detail?.connected;
 const currency=detail?.currency||"—";
 const fmt=(value:any)=>value==null||!Number.isFinite(Number(value))?"—":Number(value).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});

 return <ScrollView style={s.screen} contentContainerStyle={s.c}>
  <View style={s.header}>
   <View style={{flex:1}}>
    <Text style={s.eyebrow}>TRADEGUARD / SYSTEM CONTROL</Text>
    <Text style={s.title}>Account & Security</Text>
    <Text style={s.sub}>Cloud cTrader connection, account details and execution safeguards.</Text>
   </View>
   <View style={[s.healthChip,{borderColor:connected?colors.borderGlow:colors.border}]}>
    <View style={[s.healthDot,{backgroundColor:connected?colors.green:colors.red}]}/>
    <Text style={[s.healthText,{color:connected?colors.green:colors.red}]}>{connected?"ONLINE":"OFFLINE"}</Text>
   </View>
  </View>

  <Panel>
   <View style={s.panelHead}><View><Text style={s.label}>IDENTITY</Text><Text style={s.h}>TradeGuard Account</Text></View><Text style={s.secure}>SECURE SESSION</Text></View>
   <Text style={s.l}>Email</Text><Text style={s.v}>{account?.email??"Loading..."}</Text>
   <Pressable onPress={signOut} style={s.signOut}><Text style={s.signOutText}>SIGN OUT</Text></Pressable>
  </Panel>

  <Panel>
   <View style={s.panelHead}><View><Text style={s.label}>BROKER CONNECTION</Text><Text style={s.h}>cTrader Open API</Text></View>
    <View style={s.securePill}><Text style={s.securePillText}>{ctrader?.authorized?"AUTHORIZED":"NOT AUTHORIZED"}</Text></View>
   </View>
   <Text style={s.note}>Authorize your cTrader account through the official broker login. Selecting a Live account here only enables account inspection; automated order execution remains Demo-only.</Text>
   <Text style={s.l}>Authorization</Text><Text style={s.v}>{ctrader?.authorized?"Authorized":"Not authorized"}</Text>
   {ctrader?.account_id!=null&&<>
    <Text style={s.l}>Selected account</Text><Text style={s.v}>{ctrader.account_id}</Text>
    <Text style={s.l}>Environment</Text><Text style={[s.v,{color:isLive?colors.amber:colors.green}]}>{isLive?"LIVE · READ-ONLY ORDER MODE":"DEMO · EXECUTION TEST MODE"}</Text>
   </>}
   <Pressable disabled={ctraderBusy} onPress={ctrader?.authorized?refreshCTraderAccounts:connectCTrader} style={s.connectButton}>
    {ctraderBusy?<ActivityIndicator color="#021008"/>:<Text style={s.connectText}>{ctrader?.authorized?"REFRESH ACCOUNTS":"CONNECT cTRADER"}</Text>}
   </Pressable>
   {ctraderAccounts.map((item:any)=><Pressable key={String(item.account_id)} disabled={ctraderBusy} onPress={()=>selectCTraderAccount(Number(item.account_id))} style={[s.accountChoice,Number(ctrader?.account_id)===Number(item.account_id)&&s.accountChoiceActive]}>
    <View style={{flex:1}}><Text style={s.accountChoiceTitle}>Account {item.account_id}</Text><Text style={s.accountChoiceMeta}>Login {item.trader_login||"—"}</Text></View>
    <Text style={[s.environment,{color:item.is_live?colors.amber:colors.green}]}>{item.is_live?"LIVE":"DEMO"}</Text>
   </Pressable>)}
   {loadError!==""&&<Text style={s.error}>{loadError}</Text>}
  </Panel>

  <Panel>
   <View style={s.panelHead}><View><Text style={s.label}>BROKER ACCOUNT</Text><Text style={s.h}>Actual Account Snapshot</Text></View><Text style={s.secure}>{connected?"SYNCED":"WAITING"}</Text></View>
   {detail?.connected?<>
    <View style={s.balanceCard}><Text style={s.balanceLabel}>BALANCE</Text><Text style={s.balance}>{fmt(detail.balance)} {currency}</Text>
     <View style={s.balanceStats}><View style={{flex:1}}><Text style={s.l}>Equity</Text><Text style={s.stat}>{fmt(detail.equity)} {currency}</Text></View><View style={{flex:1}}><Text style={s.l}>Unrealized P/L</Text><Text style={[s.stat,{color:Number(detail.unrealized_pnl)>=0?colors.green:colors.red}]}>{fmt(detail.unrealized_pnl)} {currency}</Text></View></View>
    </View>
    <View style={s.accountGrid}>
     <View style={s.accountTile}><Text style={s.l}>Free margin</Text><Text style={s.v}>{fmt(detail.free_margin)} {currency}</Text></View>
     <View style={s.accountTile}><Text style={s.l}>Used margin</Text><Text style={s.v}>{fmt(detail.used_margin)} {currency}</Text></View>
     <View style={s.accountTile}><Text style={s.l}>Open positions</Text><Text style={s.v}>{detail.positions_count??"—"}</Text></View>
     <View style={s.accountTile}><Text style={s.l}>Last broker sync</Text><Text style={s.v}>{detail.updated_at?new Date(detail.updated_at).toLocaleTimeString():"—"}</Text></View>
    </View>
   </>:<Text style={s.note}>Account values appear here after the selected cTrader account has synchronized successfully. No demo placeholder values are shown.</Text>}
   {detailError!==""&&<Text style={s.error}>Broker refresh failed. Showing the last successful snapshot, which may be stale. {detailError}</Text>}
    {health?.error&&<Text style={s.error}>{health.error}</Text>}
  </Panel>

  <Panel>
   <View style={s.panelHead}><View><Text style={s.label}>AUTOMATION SAFETY</Text><Text style={s.h}>Execution Environment</Text></View><Text style={s.secure}>DEMO-ONLY</Text></View>
   <Text style={s.v}>Automated orders: cTrader Demo only</Text>
   <Text style={s.note}>Selecting a Live account never enables live order execution. Use Demo first to confirm fresh quotes, order sizing, broker acknowledgement and stop-loss/take-profit protection.</Text>
  </Panel>
 </ScrollView>
}

const s=StyleSheet.create({
 screen:{flex:1,backgroundColor:colors.background},
 c:{padding:18,paddingTop:58,gap:14,paddingBottom:112},
 header:{flexDirection:"row",justifyContent:"space-between",alignItems:"flex-start",gap:10},
 eyebrow:{color:colors.green,fontSize:8,fontWeight:"900",letterSpacing:1.5},
 title:{color:colors.text,fontSize:27,fontWeight:"900",marginTop:3},
 sub:{color:colors.muted,fontSize:10,lineHeight:15,marginTop:4},
 healthChip:{flexDirection:"row",alignItems:"center",gap:5,paddingHorizontal:9,paddingVertical:7,borderRadius:radii.pill,borderWidth:1,backgroundColor:colors.surface2},
 healthDot:{width:6,height:6,borderRadius:6},healthText:{fontSize:7,fontWeight:"900",letterSpacing:.8},
 panelHead:{flexDirection:"row",justifyContent:"space-between",alignItems:"center",marginBottom:10},
 label:{color:colors.muted,fontSize:8,fontWeight:"900",letterSpacing:1.1},
 secure:{color:colors.green,fontSize:7,fontWeight:"900",letterSpacing:.8},
 securePill:{paddingHorizontal:7,paddingVertical:5,borderRadius:radii.pill,backgroundColor:colors.surface2,borderWidth:1,borderColor:colors.borderGlow},
 securePillText:{color:colors.green,fontSize:6,fontWeight:"900",letterSpacing:.7},
 h:{color:colors.text,fontWeight:"900",fontSize:15,marginBottom:10},
 l:{color:colors.muted,fontSize:11,marginTop:7},
 v:{color:colors.text,fontSize:13,fontWeight:"700",marginTop:2},
 connectButton:{backgroundColor:colors.green,borderRadius:10,padding:13,alignItems:"center",marginTop:16},
 connectText:{color:"#021008",fontWeight:"900",fontSize:12},
 note:{color:colors.muted,fontSize:11,lineHeight:17,marginTop:12},
 accountChoice:{flexDirection:"row",alignItems:"center",marginTop:9,padding:12,borderRadius:10,borderWidth:1,borderColor:colors.border,backgroundColor:colors.surface2},
 accountChoiceActive:{borderColor:colors.green,backgroundColor:"#0d271d"},
 accountChoiceTitle:{color:colors.text,fontWeight:"900",fontSize:12},accountChoiceMeta:{color:colors.muted,fontSize:9,marginTop:4},
 environment:{fontSize:9,fontWeight:"900",marginLeft:12},
 balanceCard:{padding:14,borderRadius:12,backgroundColor:colors.surface2,borderWidth:1,borderColor:colors.borderGlow,marginTop:6},
 balanceLabel:{color:colors.muted,fontSize:8,fontWeight:"900",letterSpacing:1.3},
 balance:{color:colors.text,fontSize:27,fontWeight:"900",marginTop:6},
 balanceStats:{flexDirection:"row",gap:12,marginTop:14},
 stat:{color:colors.text,fontSize:13,fontWeight:"800",marginTop:3},
 accountGrid:{flexDirection:"row",flexWrap:"wrap",gap:10,marginTop:12},
 accountTile:{width:"47%",padding:10,borderRadius:9,backgroundColor:colors.surface2},
 error:{color:colors.red,fontSize:10,marginTop:10},
 signOut:{marginTop:14,borderWidth:1,borderColor:"#7f1d1d",borderRadius:10,padding:12,alignItems:"center"},
 signOutText:{color:"#fca5a5",fontWeight:"900",fontSize:12}
});
