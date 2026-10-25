import {AppState,ScrollView,StyleSheet,Text,View,Pressable,ActivityIndicator,Alert} from "react-native";
import {useEffect,useRef,useState} from "react";
import {colors,radii,shadows} from "../../src/theme";
import {Panel} from "../../src/components/Panel";
import {api} from "../../src/api";
import {BOT_MODES,BotMode} from "../../src/api_mode";

const BOT_MODE_LABELS:Record<BotMode,string>={
 signals_only:"SIGNALS ONLY",
 semi_auto:"SEMI-AUTO · APPROVAL ONLY",
 full_auto:"FULL AUTO · PAUSED"
};
// Full-auto execution stays disabled until the backend can verify broker-side
// risk sizing; the API rejects it too, so the button is never actionable.
const DISABLED_MODES:ReadonlySet<BotMode>=new Set<BotMode>(["full_auto"]);

export default function Bot(){
 const [b,setB]=useState<any>(null);
 const [ai,setAi]=useState<any>(null);
 const [savingAi,setSavingAi]=useState(false);
 const [actionBusy,setActionBusy]=useState(false);
 const [emergencyBusy,setEmergencyBusy]=useState(false);
 const [closeAllBusy,setCloseAllBusy]=useState(false);

 const screenMounted=useRef(false);
 const loadInFlight=useRef(false);
 const loadQueued=useRef(false);
 const load=async()=>{
  if(loadInFlight.current){loadQueued.current=true;return;}
  loadInFlight.current=true;
  try{
   const [botResult,approvalResult]=await Promise.allSettled([api.bot(),api.aiApproval()]);
   if(!screenMounted.current)return;
   if(botResult.status==="fulfilled")setB(botResult.value);
   if(approvalResult.status==="fulfilled")setAi(approvalResult.value);
   else setAi((current:any)=>current??{enabled:false,min_score:80});
  }finally{
   loadInFlight.current=false;
   if(screenMounted.current&&loadQueued.current){loadQueued.current=false;void load();}
  }
 };

 useEffect(()=>{
  screenMounted.current=true;
  void load();
  const timer=setInterval(()=>{void load()},20000);
  const sub=AppState.addEventListener("change",state=>{if(state==="active")void load()});
  return()=>{
   screenMounted.current=false;
   loadQueued.current=false;
   clearInterval(timer);
   sub.remove();
  };
 },[]);

 const action=async(fn:()=>Promise<any>)=>{
  if(actionBusy)return;
  setActionBusy(true);
  try{
   const result=await fn();
   if(screenMounted.current)setB(result);
  }catch(e:any){
   if(screenMounted.current)Alert.alert("Autopilot",e?.message||"Could not update the trading engine.");
  }finally{
   if(screenMounted.current)setActionBusy(false);
  }
 };

 async function emergencyStopNow(){
  // Emergency stop must remain usable even while a routine command is pending.
  if(emergencyBusy)return;
  setEmergencyBusy(true);
  try{
   const result=await api.emergencyStop();
   if(screenMounted.current){
    if(result&&typeof result==="object")setB((current:any)=>({...current,...((result as any).state??result)}));
    Alert.alert("Emergency stop",String((result as any)?.message||"New trading disabled. Existing cTrader positions remain open; use Close All separately if needed. Check the engine status and Alerts for confirmation."));
    void load();
   }
  }catch(e:any){
   if(screenMounted.current)Alert.alert("Emergency stop failed",String(e?.message||"Could not send emergency-stop request. Verify TradeGuard and cTrader directly."));
  }finally{
   if(screenMounted.current)setEmergencyBusy(false);
  }
 }

 async function emergencyCloseAll(){
  if(closeAllBusy)return;
  Alert.alert(
   "Emergency Close All?",
   "This submits a market-close request for every open position in the currently selected cTrader account, including Live positions. It may realize losses or incur slippage. A queued request is not proof that positions closed. Verify the result in cTrader. This does not replace Emergency Stop.",
   [
    {text:"Cancel",style:"cancel"},
    {text:"CLOSE ALL POSITIONS",style:"destructive",onPress:async()=>{
     if(closeAllBusy)return;
     setCloseAllBusy(true);
     try{
      const queued:any=await api.closeAll();
      if(queued?.status==="no_open_positions" && queued?.positions_count===0){
       Alert.alert("Close All verified","The response reports no open positions. Verify the selected account in cTrader if you need immediate confirmation.");
       return;
      }
      const rawIds=Array.isArray(queued?.command_ids)?queued.command_ids:[queued?.command_id];
      const validIds=rawIds.filter((id:any)=>typeof id==="number"&&Number.isSafeInteger(id)&&id>0);
      const commandIds=Array.from(new Set<number>(validIds));
      const invalidCommandIds=rawIds.filter((id:any)=>!(typeof id==="number"&&Number.isSafeInteger(id)&&id>0)).length;
      if(commandIds.length===0){
       Alert.alert("Close All not confirmed",String(queued?.message||"No valid command ID was returned. Check cTrader directly before retrying."));
       return;
      }
      let outcomes:any[]=[];
      try{
       outcomes=await Promise.all(commandIds.map(async(commandId:number)=>{
        let status:any=null;
        for(let attempt=0;attempt<8;attempt++){
         try{status=await api.cTraderCommand(commandId);}catch{status=null;}
         if(status?.status==="completed"||status?.status==="failed")break;
         await new Promise(resolve=>setTimeout(resolve,1500));
        }
        return status;
       }));
      }catch{
       Alert.alert("Close All pending","One or more command results could not be read. Check cTrader directly before retrying.");
       return;
      }
      if(outcomes.length===1&&outcomes[0]?.status==="completed"&&outcomes[0]?.result?.status==="no_open_positions"){
       Alert.alert("No open positions","cTrader confirmed there were no open positions in the selected account at the time of reconciliation.");
       return;
      }
      let closed=0,reduced=0,failed=0,unexpected=0,unconfirmed=invalidCommandIds;
      for(const status of outcomes){
       if(!status || (status.status!=="completed"&&status.status!=="failed")){
        unconfirmed++;
        continue;
       }
       const result=status.result;
       if(status.status==="failed" && result?.status==="submitted_unconfirmed"){
        unconfirmed++;
        continue;
       }
       if(status.status==="failed"){
        failed++;
        continue;
       }
       const positions:Array<any>=Array.isArray(result?.positions)?result.positions:
        result&&typeof result==="object"&&Object.keys(result).length>0?[result]:[];
       if(positions.length===0){
        unconfirmed++;
        continue;
       }
       for(const position of positions){
        if(position?.status==="confirmed_closed")closed++;
        else if(position?.status==="confirmed_reduced")reduced++;
        else if(position?.status==="failed")failed++;
        else if(position?.status==="changed_unexpectedly")unexpected++;
        else unconfirmed++;
       }
      }
      Alert.alert(
       "Close All results",
       closed+" fully closed; "+reduced+" partially reduced; "+failed+" failed; "+unexpected+" unexpected broker changes; "+unconfirmed+" unconfirmed. Check cTrader for any remaining positions before retrying."
      );
     }catch(e:any){
      Alert.alert("Close All error",String(e?.message||"Could not submit or verify Close All. Check cTrader directly before retrying."));
     }finally{
      if(screenMounted.current){
       setCloseAllBusy(false);
       // Refresh engine status after every outcome, including timeout and
       // malformed responses, so the emergency-stop latch is not left stale.
       void load();
      }
     }
    }}
   ]
  );
 }
 async function toggleAi(){
  if(!ai)return;
  const next=!ai.enabled;
  if(next){
   Alert.alert(
    "Enable AI Auto-Approval?",
    "When you are away, TradeGuard can approve high-confidence setups for the selected cTrader account. Automated order execution remains locked until broker-verified account-currency risk sizing is implemented and tested. This is off by default.",
    [
     {text:"Cancel",style:"cancel"},
     {text:"ENABLE",onPress:()=>saveAi(true)}
    ]
   );
  }else saveAi(false);
 }

 async function saveAi(enabled:boolean){
  setSavingAi(true);
  try{
   const result=await api.updateAiApproval({enabled,min_score:Number(ai?.min_score||80)});
   if(screenMounted.current)setAi(result);
  }catch(e:any){
   if(screenMounted.current)Alert.alert("AI Approval",e?.message||"Could not update AI approval.");
  }finally{if(screenMounted.current)setSavingAi(false)}
 }

 if(!b)return <View style={[s.loading,{padding:24,gap:14}]}>
   <ActivityIndicator color={colors.green}/>
   <Text style={s.state}>ENGINE STATUS UNAVAILABLE</Text>
   <Text style={[s.muted,{textAlign:"center"}]}>TradeGuard could not load the current bot state. You can still send a Stop Bot or Emergency Stop request; verify the result in Alerts and cTrader.</Text>
   <Pressable disabled={actionBusy} style={[s.stop,actionBusy&&{opacity:0.6}]} onPress={()=>action(api.stopBot)}><Text style={s.button}>{actionBusy?"SENDING STOP REQUEST…":"STOP BOT"}</Text></Pressable>
   <Pressable disabled={emergencyBusy} style={[s.emergency,emergencyBusy&&{opacity:0.65}]} onPress={emergencyStopNow}><Text style={s.emergencyText}>{emergencyBusy?"SENDING EMERGENCY STOP…":"EMERGENCY STOP · ALWAYS AVAILABLE"}</Text></Pressable>
  <Pressable disabled={closeAllBusy} style={[s.emergency,closeAllBusy&&{opacity:0.6}]} onPress={emergencyCloseAll}><Text style={s.emergencyText}>{closeAllBusy?"SUBMITTING / VERIFYING CLOSE ALL…":"EMERGENCY CLOSE ALL POSITIONS"}</Text></Pressable>
   <Pressable onPress={()=>void load()}><Text style={[s.modeText,{textAlign:"center"}]}>RETRY STATUS</Text></Pressable>
  </View>;

 return <ScrollView style={s.screen} contentContainerStyle={s.c}>
  <View style={s.header}><View style={{flex:1}}><Text style={s.eyebrow}>TRADEGUARD / AUTOMATION DESK</Text><Text style={s.title}>Autopilot</Text><Text style={s.sub}>Controlled automation with hard risk boundaries.</Text></View><View style={[s.statusChip,{borderColor:b.running?colors.borderGlow:colors.border}]}><View style={[s.statusDot,{backgroundColor:b.running?colors.green:colors.red}]}/><Text style={[s.statusText,{color:b.running?colors.green:colors.red}]}>{b.running?"MONITORING ACTIVE":"ENGINE IDLE"}</Text></View></View>

  <Panel>
   <View style={s.engineHead}><View><Text style={s.label}>STRATEGY MONITOR</Text><Text style={s.state}>{b.running?"ACTIVE":"IDLE"}</Text></View><View style={s.guard}><Text style={s.guardText}>RISK GUARD</Text><Text style={s.guardState}>ACTIVE</Text></View></View>
   <Text style={s.muted}>Cloud strategy monitoring is separate from order execution. Demo and Live account support is intended; new orders remain blocked until cTrader account-currency risk sizing is verified.</Text>
  </Panel>

  <Text style={s.section}>AI Approval Layer</Text>
  <Panel>
   <View style={s.aiHeader}>
    <View style={{flex:1}}>
     <Text style={s.aiTitle}>{ai?.enabled?"AI APPROVAL ON":"AI APPROVAL OFF"}</Text>
     <Text style={s.muted}>Monitor qualifying setups while away. cTrader auto-execution is currently paused until broker risk metrics and order sizing are verified.</Text>
    </View>
    <Pressable disabled={savingAi} onPress={toggleAi} style={[s.toggle,ai?.enabled&&s.toggleOn]}>
     {savingAi?<ActivityIndicator color={colors.background}/>:<View style={[s.knob,ai?.enabled&&s.knobOn]}/>}
    </Pressable>
   </View>
   <View style={s.line}><Text style={s.muted}>Minimum signal score</Text><Text style={s.value}>{ai?.min_score??80}</Text></View>
   <Text style={s.warning}>Safety: Demo and Live accounts are supported for account monitoring and manual position controls. Automated entries remain paused for both until broker-verified account-currency risk sizing and execution checks are implemented and tested. Enabling AI approval does not mean orders are being executed.</Text>
  </Panel>

  <View style={s.executionBanner}><View style={s.executionLock}><Text style={s.executionTitle}>ORDER ROUTING LOCKED</Text><Text style={s.executionCopy}>No automated entries are sent to cTrader while broker-verified volume sizing is unavailable.</Text></View></View>
  <Text style={s.section}>Execution Mode</Text>
  <Panel>{BOT_MODES.map(m=><Pressable key={m} disabled={actionBusy||DISABLED_MODES.has(m)} onPress={()=>action(()=>api.updateMode(m))} style={[s.mode,b.mode===m?s.active:null,(actionBusy||DISABLED_MODES.has(m))&&{opacity:0.55}]}><Text style={s.modeText}>{BOT_MODE_LABELS[m]}</Text></Pressable>)}</Panel>

  <Text style={s.section}>Risk Command</Text>
  <Panel>
   <View style={s.riskBanner}><Text style={s.label}>PROTECTION PROFILE</Text><Text style={s.protected}>HARD RISK LIMITS ACTIVE</Text></View>
   <View style={s.line}><Text style={s.muted}>Risk / trade</Text><Text style={s.value}>{b.risk_per_trade??0.5}%</Text></View>
   <View style={s.line}><Text style={s.muted}>Daily loss limit</Text><Text style={s.value}>{b.daily_loss_limit??2}%</Text></View>
   <View style={s.line}><Text style={s.muted}>Max open trades</Text><Text style={s.value}>{b.max_open_trades??3}</Text></View>
   <View style={s.line}><Text style={s.muted}>Max drawdown</Text><Text style={s.value}>{b.max_drawdown??5}%</Text></View>
  </Panel>

  <Pressable disabled={actionBusy} style={[s.stop,actionBusy&&{opacity:0.6}]} onPress={()=>action(b.running?api.stopBot:api.startBot)}><Text style={s.button}>{actionBusy?"UPDATING ENGINE…":b.running?"STOP BOT":"START BOT"}</Text></Pressable>
  <Pressable disabled={emergencyBusy} style={[s.emergency,emergencyBusy&&{opacity:0.65}]} onPress={emergencyStopNow}><Text style={s.emergencyText}>{emergencyBusy?"SENDING EMERGENCY STOP…":"EMERGENCY STOP · ALWAYS AVAILABLE"}</Text></Pressable>
  <Pressable disabled={closeAllBusy} style={[s.emergency,closeAllBusy&&{opacity:0.6}]} onPress={emergencyCloseAll}><Text style={s.emergencyText}>{closeAllBusy?"SUBMITTING / VERIFYING CLOSE ALL…":"EMERGENCY CLOSE ALL POSITIONS"}</Text></Pressable>
 </ScrollView>
}

const s=StyleSheet.create({
 screen:{flex:1,backgroundColor:colors.background},
 loading:{flex:1,backgroundColor:colors.background,alignItems:"center",justifyContent:"center"},
 c:{padding:18,paddingTop:58,paddingBottom:112,gap:14},
 header:{flexDirection:"row",justifyContent:"space-between",alignItems:"flex-start",gap:10},
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
 executionBanner:{borderWidth:1,borderColor:colors.amber+"66",backgroundColor:colors.surface2,borderRadius:10,padding:13},executionLock:{gap:5},executionTitle:{color:colors.amber,fontSize:10,fontWeight:"900",letterSpacing:.8},executionCopy:{color:colors.muted,fontSize:10,lineHeight:15},
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