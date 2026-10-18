import {ScrollView,StyleSheet,Text,View,Pressable,ActivityIndicator,Alert} from "react-native";
import {useEffect,useRef,useState} from "react";
import {AppState} from "react-native";
import {Ionicons} from "@expo/vector-icons";
import {colors,radii,shadows} from "../../src/theme";
import {Panel} from "../../src/components/Panel";
import {api} from "../../src/api";
import {isCTraderSnapshotFresh} from "../../src/ctraderSnapshot";
import {onCTraderAccountChanged} from "../../src/ctraderAccountEvents";

export default function Bot(){
 const [b,setB]=useState<any>(null);
 const [cloud,setCloud]=useState<any>(null);
 const [snapshot,setSnapshot]=useState<any>(null);
 const [accountMetrics,setAccountMetrics]=useState<any>(null);
 const [busy,setBusy]=useState(false);
 const [refreshing,setRefreshing]=useState(false);
 const [error,setError]=useState("");
 const [statusWarnings,setStatusWarnings]=useState<string[]>([]);
 const [botStatusVerified,setBotStatusVerified]=useState(false);
 const loadId=useRef(0);
 const accountGeneration=useRef(0);
 const mounted=useRef(true);
 const loadInFlight=useRef(false);
 const refreshQueued=useRef(false);

 const performLoad=async()=>{
  const request=++loadId.current;
  setRefreshing(true);
  setBotStatusVerified(false);
  try{
   // Load the selected account identity before requesting its broker snapshot.
   // The snapshot validator below depends on this connection response being current.
   const results=await Promise.allSettled([api.bot(),api.account(),api.ctraderConnection()]);
   if(!mounted.current||request!==loadId.current)return;
   const snapshotResult:PromiseSettledResult<any>=results[2].status==="fulfilled"
    ?(await Promise.allSettled([api.ctraderAccountSnapshot()]))[0]
    :{status:"rejected",reason:new Error("cTrader connection unavailable; snapshot request skipped.")};
   if(!mounted.current||request!==loadId.current)return;
   const warnings:string[]=[];
   const botResult=results[0];
   if(botResult.status==="fulfilled"){setB(botResult.value);setBotStatusVerified(true);}
   else{
    warnings.push("Automation status could not be refreshed.");
    setError((botResult.reason as any)?.message||"Could not load the automation status. Check your connection and retry.");
   }
   const cloudValue=results[2].status==="fulfilled"?results[2].value:null;
   const snapshotValue=snapshotResult.status==="fulfilled"?snapshotResult.value:null;
   if(cloudValue)setCloud(cloudValue);
   else {setCloud(null);setSnapshot(null);setAccountMetrics(null);warnings.push("cTrader connection status is unavailable. Broker account metrics are withheld.");}
   const cloudId=cloudValue?.account_id==null?"":String(cloudValue.account_id).trim();
   const snapshotId=snapshotValue?.account_id==null?"":String(snapshotValue.account_id).trim();
   const cloudEnvironment=String(cloudValue?.environment??"").trim().toLowerCase();
   const snapshotEnvironment=String(snapshotValue?.environment??"").trim().toLowerCase();
   const snapshotFresh=isCTraderSnapshotFresh(snapshotValue);
   // Risk approval needs a complete broker snapshot, not merely a fresh timestamp.
   // Balance and positions must both be represented before account metrics can be trusted.
   const snapshotComplete=snapshotValue?.snapshot_status==="complete"&&snapshotValue?.balance_status!=="unavailable"&&snapshotValue?.positions_status!=="unavailable";
   const identityMatches=!!cloudValue?.connected&&!!cloudId&&!!snapshotId&&cloudId===snapshotId&&!!cloudEnvironment&&cloudEnvironment===snapshotEnvironment&&snapshotFresh&&snapshotComplete;
   if(identityMatches)setSnapshot(snapshotValue);
   else {
    setSnapshot(null);
    if(!snapshotValue)warnings.push("cTrader account snapshot is stale or unavailable.");
    else if(!snapshotFresh)warnings.push("Snapshot timestamp missing, invalid, or older than 60 seconds; broker metrics remain unverified.");
    else if(!snapshotComplete)warnings.push("Broker snapshot is incomplete or balance/positions data is unavailable. Risk approval remains locked.");
    else warnings.push("Broker snapshot does not match a confirmed selected account. Previous account values are withheld.");
   }
   if(results[1].status==="fulfilled"&&identityMatches)setAccountMetrics(results[1].value);
   else {setAccountMetrics(null);if(results[1].status!=="fulfilled")warnings.push("Account risk metrics are stale or unavailable.");}
   if(cloudValue&&snapshotValue){
    if(!cloudId||!snapshotId)warnings.push("Selected cTrader account ID is missing from the connection or snapshot.");
    else if(cloudId!==snapshotId)warnings.push("Selected cTrader account ID conflicts with the broker snapshot.");
    if(!cloudEnvironment||!snapshotEnvironment)warnings.push("cTrader account environment could not be verified.");
    else if(cloudEnvironment!==snapshotEnvironment)warnings.push("cTrader connection and snapshot environments conflict.");
    if(cloudEnvironment!=="demo"||snapshotEnvironment!=="demo")warnings.push("Only a verified demo account is permitted; execution is locked.");
    if(!cloudValue.connected)warnings.push("The selected cTrader cloud account is not currently connected.");
   }
   setStatusWarnings([...new Set(warnings)]);
   if(botResult.status==="fulfilled"){
    setError(warnings.length?"Some broker/account status checks failed. Treat displayed account information as unverified until refresh succeeds.":"");
   }
  }catch(e:any){
   if(mounted.current&&request===loadId.current){setBotStatusVerified(false);setCloud(null);setSnapshot(null);setAccountMetrics(null);setStatusWarnings(["Refresh failed; broker values are withheld until a fresh check succeeds."]);setError(e?.message||"Status refresh failed. Retry when connected.");}
  }finally{
   if(mounted.current&&request===loadId.current)setRefreshing(false);
  }
 };

 const load=async()=>{
  // Coalesce timer, foreground, manual, and account-change refreshes.
  // If a request is already running, schedule one follow-up instead of
  // starting another overlapping batch of broker requests.
  if(loadInFlight.current){refreshQueued.current=true;return;}
  loadInFlight.current=true;
  try{
   do{
    refreshQueued.current=false;
    await performLoad();
   }while(refreshQueued.current&&mounted.current);
  }finally{
   loadInFlight.current=false;
   if(refreshQueued.current&&mounted.current)void load();
  }
 };

 useEffect(()=>{
  mounted.current=true;
  let active=AppState.currentState==="active";
  let timer:ReturnType<typeof setInterval>|undefined;
  void load();
  // Keep the 60-second snapshot freshness gate current while the screen is open.
  timer=setInterval(()=>{if(active)void load();},15000);
  const appStateSub=AppState.addEventListener("change",state=>{
   const wasActive=active;
   active=state==="active";
   if(active&&!wasActive)void load();
  });
  const unsubscribe=onCTraderAccountChanged(()=>{
   // Invalidate action readbacks as well as ordinary refresh responses for the old account.
   accountGeneration.current+=1;
   loadId.current+=1;
   setCloud(null);setSnapshot(null);setAccountMetrics(null);
   setStatusWarnings(["cTrader account changed. Waiting for fresh account and risk verification."]);
   setError("Account changed. Previous account metrics are withheld until refreshed.");
   void load();
  });
  return()=>{unsubscribe();appStateSub.remove();if(timer)clearInterval(timer);mounted.current=false;loadId.current+=1};
 },[]);

 const action=async(fn:()=>Promise<any>,verify?:((state:any)=>boolean),allowDuringRefresh=false)=>{
  if(busy||(refreshing&&!allowDuringRefresh))return;
  const actionGeneration=accountGeneration.current;
  const accountChanged=()=>actionGeneration!==accountGeneration.current;
  setBusy(true);
  try{
   setError("");
   await fn();
   if(accountChanged()){void load();return;}
   await load();
   if(accountChanged()){void load();return;}
   // A successful HTTP response only confirms receipt, not the resulting engine state.
   // Read back the authoritative bot state before treating a state-changing action as done.
   if(verify){
    const confirmed=await api.bot();
    if(!mounted.current)return;
    if(accountChanged()){void load();return;}
    if(!verify(confirmed))throw new Error("The server accepted the request, but the requested state could not be confirmed. Refresh status before trying again.");
    setB(confirmed);
    setBotStatusVerified(true);
   }
  }catch(error:any){
   // A timeout/network error can happen after the server has already applied the action.
   // Reconcile against server state; never automatically repeat a potentially completed command.
   let reconciled=false;
   try{
    const confirmed=await api.bot();
    if(mounted.current&&!accountChanged()){
     setB(confirmed);
     setBotStatusVerified(true);
     reconciled=!!verify&&verify(confirmed);
    }
   }catch{}
   if(!mounted.current)return;
   if(accountChanged()){void load();return;}
   void load();
   if(reconciled){
    Alert.alert("Action confirmed","The request returned an error, but the server now reports the requested state. No retry is needed.");
   }else{
    Alert.alert("Action result unconfirmed","TradeGuard could not verify whether the server completed this action. Status is being refreshed; do not repeat the action until the current state is confirmed. "+(error?.message||"The connection may have timed out."));
   }
  }finally{
   if(mounted.current)setBusy(false);
  }
 };

 const environment=String(snapshot?.environment??cloud?.environment??"").trim().toLowerCase();
 const environmentIsDemo=environment==="demo";
 const environmentIsLive=environment==="live";
 const snapshotAccountId=snapshot?.account_id==null?"":String(snapshot.account_id).trim();
 const cloudAccountId=cloud?.account_id==null?"":String(cloud.account_id).trim();
 const snapshotEnvironment=String(snapshot?.environment??"").trim().toLowerCase();
 const cloudEnvironment=String(cloud?.environment??"").trim().toLowerCase();
 const accountIdentityConsistent=!!snapshotAccountId&&!!cloudAccountId&&snapshotAccountId===cloudAccountId&&snapshotEnvironment==="demo"&&cloudEnvironment==="demo"&&!!cloud?.connected;
 const metricsVerified=!!accountMetrics?.account_metrics_available&&environmentIsDemo&&accountIdentityConsistent&&statusWarnings.length===0;
 const riskPerTrade=Number(b?.risk_per_trade);
 const dailyLossLimit=Number(b?.daily_loss_limit);
 const maxOpenTrades=Number(b?.max_open_trades);
 const maxDrawdown=Number(b?.max_drawdown);
 const riskSettingsValid=Number.isFinite(riskPerTrade)&&riskPerTrade>=0.1&&riskPerTrade<=5&&Number.isFinite(dailyLossLimit)&&dailyLossLimit>=0.5&&dailyLossLimit<=20&&Number.isInteger(maxOpenTrades)&&maxOpenTrades>=1&&maxOpenTrades<=20&&Number.isFinite(maxDrawdown)&&maxDrawdown>=1&&maxDrawdown<=50;
 const statusFresh=botStatusVerified&&!refreshing&&!error&&statusWarnings.length===0;
 const emergencyStopped=botStatusVerified&&!!b?.emergency_stopped;
 const emergencyStatus=botStatusVerified?(emergencyStopped?"EMERGENCY STOP ACTIVE":"EMERGENCY STOP CLEAR"):"EMERGENCY STATUS UNKNOWN";
 const riskStatus=!botStatusVerified?"BOT STATUS UNVERIFIED":emergencyStopped?"EMERGENCY STOP ACTIVE":environmentIsLive?"LIVE ACCOUNT · EXECUTION LOCKED":!accountIdentityConsistent?"ACCOUNT IDENTITY UNVERIFIED":!riskSettingsValid?"RISK SETTINGS INVALID":metricsVerified?"RISK METRICS VERIFIED":"RISK METRICS UNVERIFIED";
 const riskColor=!botStatusVerified||!riskSettingsValid||emergencyStopped||environmentIsLive?colors.red:metricsVerified?colors.green:colors.amber;

 if(!b)return <View style={s.loading}>{refreshing||busy?<ActivityIndicator color={colors.green}/>:<><Text style={s.error}>{error||"Automation status unavailable."}</Text><Pressable disabled={refreshing||busy} style={s.retry} onPress={()=>{setError("");void load()}}><Text style={s.retryText}>RETRY STATUS</Text></Pressable></>}</View>;

 return <ScrollView style={s.screen} contentContainerStyle={s.c}>
  {error?<Panel><Text style={s.error}>Status refresh warning: {error} Last successful values may be stale and must not be treated as verified.</Text><Pressable disabled={refreshing||busy} style={s.retry} onPress={()=>{setError("");void load()}}><Text style={s.retryText}>{refreshing?"REFRESHING…":"RETRY STATUS"}</Text></Pressable></Panel>:null}{statusWarnings.length>0&&!error?<Panel><Text style={s.error}>Broker/account verification incomplete: {statusWarnings.join(" ")}</Text></Panel>:null}
  <View style={s.header}><View style={{flex:1}}><Text style={s.eyebrow}>TRADEGUARD  /  CONTROL CENTER</Text><Text style={s.title}>Autopilot</Text><Text style={s.sub}>Precision monitoring. Risk-first execution.</Text></View><View style={s.headerIcon}><Ionicons name="hardware-chip-outline" size={25} color={colors.green}/></View></View>
  <View style={s.statusBar}><View style={[s.statusDot,{backgroundColor:refreshing||!botStatusVerified?colors.amber:b.running?colors.green:colors.amber}]}/><Text style={[s.statusText,{color:refreshing||!botStatusVerified?colors.amber:b.running?colors.green:colors.amber}]}>{refreshing?"SYNCING STATUS…":!botStatusVerified?"BOT STATUS UNVERIFIED":b.running?"ENGINE ACTIVE":"ENGINE STANDBY"}</Text><View style={s.statusDivider}/><Ionicons name="shield-checkmark-outline" size={13} color={riskColor}/><Text style={[s.statusText,{color:riskColor}]}>{riskStatus}</Text></View>

  <Panel>
   <View style={s.engineHead}><View><Text style={s.label}>SYSTEM STATUS</Text><Text style={[s.state,{color:botStatusVerified?(b.running?colors.green:colors.amber):colors.amber}]}>{botStatusVerified?(b.running?"MONITORING":"ON STANDBY"):(b.running?"LAST KNOWN: MONITORING":"LAST KNOWN: STANDBY")}</Text>{!botStatusVerified?<Text style={s.warning}>Current engine state has not been confirmed by the latest server response.</Text>:null}</View><View style={s.engineIcon}><Ionicons name={botStatusVerified&&b.running?"pulse":"pause-circle-outline"} size={24} color={botStatusVerified&&b.running?colors.green:colors.amber}/></View></View>
   <View style={s.divider}/>
   <View style={s.line}><Text style={s.muted}>Broker</Text><Text style={s.value}>cTrader Cloud</Text></View>
   <View style={s.line}><Text style={s.muted}>Environment</Text><Text style={[s.value,{color:environmentIsDemo&&accountIdentityConsistent?colors.green:colors.amber}]}>{environmentIsDemo&&accountIdentityConsistent?"DEMO VERIFIED":environmentIsLive?"LIVE · LOCKED":"UNVERIFIED · LOCKED"}</Text></View>
   <View style={s.line}><Text style={s.muted}>Selected account</Text><Text style={[s.value,{color:accountIdentityConsistent?colors.green:colors.red}]}>{!snapshotAccountId||!cloudAccountId?"MISSING ID":snapshotAccountId===cloudAccountId?snapshotAccountId:"ID CONFLICT"}</Text></View>
   <Text style={s.muted}>Monitoring and signals do not imply that broker orders are enabled. Conflicting or unverified account identity keeps mode changes and bot start locked.</Text><Pressable disabled={refreshing||busy} style={[s.retry,{opacity:refreshing||busy?0.55:1}]} onPress={()=>{void load()}}><Text style={s.retryText}>{refreshing?"REFRESHING STATUS…":"REFRESH BROKER & RISK STATUS"}</Text></Pressable>
  </Panel>

  <Text style={s.section}>Execution Safety</Text>
  <Panel>
   <View style={s.safetyHead}><View style={s.safetyIcon}><Ionicons name="lock-closed" size={17} color={colors.amber}/></View><View style={{flex:1}}><Text style={s.aiTitle}>AUTO-EXECUTION LOCKED</Text><Text style={s.safetyTag}>SAFETY INTERLOCK ENABLED</Text></View></View>
   <Text style={s.muted}>Signals and risk analysis may continue. Broker orders remain blocked until account verification, broker-volume sizing, fresh quotes and mandatory stop-loss/take-profit protection pass end-to-end tests.</Text>
  </Panel>

  <Text style={s.section}>Execution Mode</Text>
  <Panel>{["signals_only","semi_auto"].map(m=><Pressable key={m} disabled={busy||refreshing||!statusFresh||!riskSettingsValid||emergencyStopped} onPress={()=>action(()=>api.updateMode(m),state=>state?.mode===m) style={[s.mode,b.mode===m?s.active:null,(busy||refreshing||!statusFresh||!riskSettingsValid||emergencyStopped)&&{opacity:0.55}]}><Text style={s.modeText}>{m==="signals_only"?"SIGNALS ONLY":m==="semi_auto"?"SEMI-AUTO · SIGNAL ONLY":"SIGNALS ONLY"}</Text></Pressable>)}</Panel>

  <Text style={s.section}>Risk Command</Text>
  <Panel>
   <View style={s.riskBanner}><Text style={s.label}>PROTECTION PROFILE</Text><Text style={[s.protected,{color:riskColor}]}>{metricsVerified&&!emergencyStopped?"CONFIGURED LIMITS · METRICS VERIFIED":emergencyStopped?"EMERGENCY STOP ACTIVE":"LIMITS CONFIGURED · METRICS UNVERIFIED"}</Text></View>
   <View style={s.line}><Text style={s.muted}>Risk / trade</Text><Text style={s.value}>{b.risk_per_trade??0.5}%</Text></View>
   <View style={s.line}><Text style={s.muted}>Daily loss limit</Text><Text style={s.value}>{b.daily_loss_limit??2}%</Text></View>
   <View style={s.line}><Text style={s.muted}>Max open trades</Text><Text style={s.value}>{b.max_open_trades??3}</Text></View>
   <View style={s.line}><Text style={s.muted}>Max drawdown</Text><Text style={s.value}>{b.max_drawdown??5}%</Text></View>
   <View style={s.line}><Text style={s.muted}>Emergency state</Text><Text style={[s.value,{color:botStatusVerified?(emergencyStopped?colors.red:colors.green):colors.amber}]}>{emergencyStatus}</Text></View>
   {!riskSettingsValid?<Text style={s.error}>Risk settings are outside the accepted ranges. Starting the engine and changing mode are disabled until settings are corrected.</Text>:null}
   {!statusFresh?<Text style={s.warning}>A fresh, complete bot status check is required before starting or changing execution mode.</Text>:null}
  </Panel>

  <Pressable disabled={busy||(b.running?false:(!statusFresh||!riskSettingsValid||emergencyStopped))} style={[s.stop,(busy||(!b.running&&(!statusFresh||!riskSettingsValid||emergencyStopped)))&&{opacity:0.55}]} onPress={()=>action(b.running?api.stopBot:api.startBot,state=>state?.running===!b.running,b.running)}><Text style={s.button}>{busy?"PLEASE WAIT…":b.running?"STOP BOT":"START BOT"}</Text></Pressable>
  <Pressable disabled={busy} style={[s.emergency,busy&&{opacity:0.55}]} onPress={()=>action(api.emergencyStop,state=>state?.emergency_stopped===true,true)}><Text style={s.emergencyText}>EMERGENCY STOP</Text></Pressable>
 </ScrollView>
}

const s=StyleSheet.create({
 screen:{flex:1,backgroundColor:colors.background},
 loading:{flex:1,backgroundColor:colors.background,alignItems:"center",justifyContent:"center",padding:24,gap:12},
 error:{color:"#ffb5bf",fontSize:11,lineHeight:16},
 retry:{marginTop:10,borderRadius:10,padding:11,alignItems:"center",backgroundColor:"#123e2b"},
 retryText:{color:colors.white,fontWeight:"900",fontSize:10},
 c:{padding:18,paddingTop:58,paddingBottom:112,gap:14},
 header:{flexDirection:"row",justifyContent:"space-between",alignItems:"center",gap:10},
 headerIcon:{width:54,height:54,borderRadius:18,backgroundColor:"#0a261c",borderWidth:1,borderColor:colors.borderGlow,alignItems:"center",justifyContent:"center",...shadows.glow},
 statusBar:{flexDirection:"row",alignItems:"center",gap:8,borderWidth:1,borderColor:colors.border,backgroundColor:colors.surface2,borderRadius:12,paddingHorizontal:12,paddingVertical:11},
 statusDivider:{height:15,width:1,backgroundColor:colors.border,marginHorizontal:2},
 engineIcon:{width:46,height:46,borderRadius:15,backgroundColor:colors.surface2,borderWidth:1,borderColor:colors.border,alignItems:"center",justifyContent:"center"},
 divider:{height:1,backgroundColor:colors.border,marginVertical:13},
 safetyHead:{flexDirection:"row",alignItems:"center",gap:10,marginBottom:9},
 safetyIcon:{width:38,height:38,borderRadius:12,backgroundColor:"#302716",borderWidth:1,borderColor:"#7a5b2c",alignItems:"center",justifyContent:"center"},
 safetyTag:{color:colors.amber,fontSize:7,fontWeight:"900",letterSpacing:.8,marginTop:4},
 eyebrow:{color:colors.green,fontSize:8,fontWeight:"900",letterSpacing:1.5},
 title:{color:colors.text,fontSize:28,fontWeight:"900",marginTop:3},
 sub:{color:colors.muted,fontSize:10,lineHeight:15,marginTop:4},
 statusChip:{flexDirection:"row",alignItems:"center",gap:5,paddingHorizontal:9,paddingVertical:7,borderRadius:radii.pill,borderWidth:1,backgroundColor:colors.surface2},
 statusDot:{width:6,height:6,borderRadius:6},statusText:{fontSize:7,fontWeight:"900",letterSpacing:.8},
 label:{color:colors.muted,fontSize:8,fontWeight:"900",letterSpacing:1.1},
 engineHead:{flexDirection:"row",justifyContent:"space-between",alignItems:"center"},
 guard:{alignItems:"flex-end"},guardText:{color:colors.muted,fontSize:7,fontWeight:"900",letterSpacing:1},guardState:{color:colors.green,fontSize:10,fontWeight:"900",marginTop:3},
 riskBanner:{backgroundColor:colors.surface2,borderRadius:10,padding:10,marginBottom:7,borderWidth:1,borderColor:colors.border},
 protected:{color:colors.green,fontSize:9,fontWeight:"900",marginTop:4},

 state:{color:colors.green,fontSize:18,fontWeight:"900"},
 muted:{color:colors.muted,fontSize:12,marginTop:5},
 section:{color:colors.text,fontSize:16,fontWeight:"800"},
 aiHeader:{flexDirection:"row",alignItems:"center",gap:12},
 aiTitle:{color:colors.text,fontSize:14,fontWeight:"900"},
 toggle:{width:50,height:30,borderRadius:20,backgroundColor:"#24352d",padding:3,justifyContent:"center"},
 toggleOn:{backgroundColor:colors.green},
 knob:{width:24,height:24,borderRadius:12,backgroundColor:"#9aa8a2"},
 knobOn:{alignSelf:"flex-end",backgroundColor:colors.background},
 warning:{color:"#f6c76b",fontSize:11,lineHeight:16,marginTop:12},
 mode:{padding:13,borderRadius:12,borderWidth:1,borderColor:colors.border,marginBottom:9},
 active:{borderColor:colors.green,backgroundColor:"#0d271d"},
 modeText:{color:colors.text,fontWeight:"800"},
 line:{flexDirection:"row",justifyContent:"space-between",paddingVertical:10},
 value:{color:colors.text,fontWeight:"900"},
 stop:{height:56,borderRadius:16,backgroundColor:colors.green,alignItems:"center",justifyContent:"center"},
 button:{color:colors.background,fontWeight:"900"},
 emergency:{height:56,borderRadius:16,backgroundColor:"#a51f34",alignItems:"center",justifyContent:"center"},
 emergencyText:{color:colors.white,fontWeight:"900",fontSize:14}
});