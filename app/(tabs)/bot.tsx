import {ScrollView,StyleSheet,Text,View,Pressable,ActivityIndicator,Alert} from "react-native";
import {useEffect,useState} from "react";
import {Ionicons} from "@expo/vector-icons";
import {colors,radii,shadows} from "../../src/theme";
import {Panel} from "../../src/components/Panel";
import {api} from "../../src/api";

export default function Bot(){
 const [b,setB]=useState<any>(null);
 const [cloud,setCloud]=useState<any>(null);
 const [snapshot,setSnapshot]=useState<any>(null);
 const [accountMetrics,setAccountMetrics]=useState<any>(null);
 const [busy,setBusy]=useState(false);
 const [error,setError]=useState("");

 const load=async()=>{
  const results=await Promise.allSettled([api.bot(),api.ctraderConnection(),api.ctraderAccountSnapshot(),api.account()]);
  const botResult=results[0];
  if(botResult.status==="fulfilled"){setB(botResult.value);setError("");}
  else setError((botResult.reason as any)?.message||"Could not load the automation status. Check your connection and retry.");
  if(results[1].status==="fulfilled")setCloud(results[1].value);
  if(results[2].status==="fulfilled")setSnapshot(results[2].value);
  if(results[3].status==="fulfilled")setAccountMetrics(results[3].value);
 };

 useEffect(()=>{void load()},[]);

 const action=async(fn:()=>Promise<any>)=>{
  if(busy)return;
  setBusy(true);
  try{
   setError("");
   await fn();
   await load();
  }catch(error:any){
   Alert.alert("Autopilot action failed",error?.message||"TradeGuard could not update the engine. Check your connection and try again.");
  }finally{
   setBusy(false);
  }
 };

 const environment=String(snapshot?.environment??cloud?.environment??"").trim().toLowerCase();
 const environmentIsDemo=environment.includes("demo");
 const environmentIsLive=environment.includes("live");
 const metricsVerified=!!accountMetrics?.account_metrics_available&&environmentIsDemo;
 const emergencyStopped=!!b?.emergency_stopped;
 const riskStatus=emergencyStopped?"EMERGENCY STOP ACTIVE":environmentIsLive?"LIVE ACCOUNT · EXECUTION LOCKED":metricsVerified?"RISK METRICS VERIFIED":"RISK METRICS UNVERIFIED";
 const riskColor=emergencyStopped||environmentIsLive?colors.red:metricsVerified?colors.green:colors.amber;

 if(!b)return <View style={s.loading}>{busy||!error?<ActivityIndicator color={colors.green}/>:<><Text style={s.error}>{error}</Text><Pressable style={s.retry} onPress={()=>{setError("");void load()}}><Text style={s.retryText}>RETRY STATUS</Text></Pressable></>}</View>;

 return <ScrollView style={s.screen} contentContainerStyle={s.c}>
  {error?<Panel><Text style={s.error}>Status refresh failed: {error}. Showing the last successful engine state.</Text><Pressable style={s.retry} onPress={()=>{setError("");void load()}}><Text style={s.retryText}>RETRY STATUS</Text></Pressable></Panel>:null}
  <View style={s.header}><View style={{flex:1}}><Text style={s.eyebrow}>TRADEGUARD  /  CONTROL CENTER</Text><Text style={s.title}>Autopilot</Text><Text style={s.sub}>Precision monitoring. Risk-first execution.</Text></View><View style={s.headerIcon}><Ionicons name="hardware-chip-outline" size={25} color={colors.green}/></View></View>
  <View style={s.statusBar}><View style={[s.statusDot,{backgroundColor:b.running?colors.green:colors.amber}]}/><Text style={[s.statusText,{color:b.running?colors.green:colors.amber}]}>{b.running?"ENGINE ACTIVE":"ENGINE STANDBY"}</Text><View style={s.statusDivider}/><Ionicons name="shield-checkmark-outline" size={13} color={riskColor}/><Text style={[s.statusText,{color:riskColor}]}>{riskStatus}</Text></View>

  <Panel>
   <View style={s.engineHead}><View><Text style={s.label}>SYSTEM STATUS</Text><Text style={s.state}>{b.running?"MONITORING":"ON STANDBY"}</Text></View><View style={s.engineIcon}><Ionicons name={b.running?"pulse":"pause-circle-outline"} size={24} color={b.running?colors.green:colors.amber}/></View></View>
   <View style={s.divider}/>
   <View style={s.line}><Text style={s.muted}>Broker</Text><Text style={s.value}>cTrader Cloud</Text></View>
   <View style={s.line}><Text style={s.muted}>Environment</Text><Text style={[s.value,{color:environmentIsDemo?colors.green:colors.amber}]}>{environmentIsDemo?"DEMO VERIFIED":environmentIsLive?"LIVE · LOCKED":"UNVERIFIED · LOCKED"}</Text></View>
   <Text style={s.muted}>Monitoring and signals do not imply that broker orders are enabled.</Text>
  </Panel>

  <Text style={s.section}>Execution Safety</Text>
  <Panel>
   <View style={s.safetyHead}><View style={s.safetyIcon}><Ionicons name="lock-closed" size={17} color={colors.amber}/></View><View style={{flex:1}}><Text style={s.aiTitle}>AUTO-EXECUTION LOCKED</Text><Text style={s.safetyTag}>SAFETY INTERLOCK ENABLED</Text></View></View>
   <Text style={s.muted}>Signals and risk analysis may continue. Broker orders remain blocked until account verification, broker-volume sizing, fresh quotes and mandatory stop-loss/take-profit protection pass end-to-end tests.</Text>
  </Panel>

  <Text style={s.section}>Execution Mode</Text>
  <Panel>{["signals_only","semi_auto"].map(m=><Pressable key={m} disabled={busy} onPress={()=>action(()=>api.updateMode(m))} style={[s.mode,b.mode===m?s.active:null,busy&&{opacity:0.55}]}><Text style={s.modeText}>{m==="signals_only"?"SIGNALS ONLY":m==="semi_auto"?"SEMI-AUTO · SIGNAL ONLY":"SIGNALS ONLY"}</Text></Pressable>)}</Panel>

  <Text style={s.section}>Risk Command</Text>
  <Panel>
   <View style={s.riskBanner}><Text style={s.label}>PROTECTION PROFILE</Text><Text style={[s.protected,{color:riskColor}]}>{metricsVerified&&!emergencyStopped?"CONFIGURED LIMITS · METRICS VERIFIED":emergencyStopped?"EMERGENCY STOP ACTIVE":"LIMITS CONFIGURED · METRICS UNVERIFIED"}</Text></View>
   <View style={s.line}><Text style={s.muted}>Risk / trade</Text><Text style={s.value}>{b.risk_per_trade??0.5}%</Text></View>
   <View style={s.line}><Text style={s.muted}>Daily loss limit</Text><Text style={s.value}>{b.daily_loss_limit??2}%</Text></View>
   <View style={s.line}><Text style={s.muted}>Max open trades</Text><Text style={s.value}>{b.max_open_trades??3}</Text></View>
   <View style={s.line}><Text style={s.muted}>Max drawdown</Text><Text style={s.value}>{b.max_drawdown??5}%</Text></View>
  </Panel>

  <Pressable disabled={busy} style={[s.stop,busy&&{opacity:0.55}]} onPress={()=>action(b.running?api.stopBot:api.startBot)}><Text style={s.button}>{busy?"PLEASE WAIT…":b.running?"STOP BOT":"START BOT"}</Text></Pressable>
  <Pressable disabled={busy} style={[s.emergency,busy&&{opacity:0.55}]} onPress={()=>action(api.emergencyStop)}><Text style={s.emergencyText}>EMERGENCY STOP</Text></Pressable>
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