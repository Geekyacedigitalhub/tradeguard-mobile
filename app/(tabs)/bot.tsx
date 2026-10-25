import {ActivityIndicator, Alert, AppState, Pressable, ScrollView, StyleSheet, Text, View} from "react-native";
import {useEffect, useRef, useState} from "react";
import {Ionicons} from "@expo/vector-icons";
import {colors,radii,shadows} from "../../src/theme";
import {api,apiErrorStatus} from "../../src/api";
import {BOT_MODES,BotMode} from "../../src/api_mode";
import {
  Chip,
  FeedRow,
  Gauge,
  PanelCard,
  Pulse,
  SectionTitle,
  Segmented,
  Stat,
  Stepper,
  Toggle,
  formatAge,
  useNow,
} from "../../src/components/ui";

const BOT_MODE_OPTIONS:ReadonlyArray<{key:BotMode;label:string;hint:string}>=BOT_MODES.map(mode=>({
  key:mode,
  label:mode==="signals_only"?"SIGNALS ONLY":mode==="semi_auto"?"SEMI-AUTO":"FULL AUTO",
  hint:mode==="signals_only"?"Alert only":mode==="semi_auto"?"Approval needed":"Locked by backend",
}));
// Full-auto execution stays disabled until the backend can verify broker-side
// risk sizing; the API rejects it too, so the option is never actionable.
const DISABLED_MODES:ReadonlySet<BotMode>=new Set<BotMode>(["full_auto"]);

type RiskDraft={risk:number;daily:number;maxOpen:number;maxDd:number};

const num=(value:any):number|null=>{
  if(value===null||value===undefined||value==="") return null;
  const parsed=Number(value);
  return Number.isFinite(parsed)?parsed:null;
};

function money(value:number|null,currency:string,decimals=2):string{
  if(value===null) return "—";
  return `${value.toLocaleString(undefined,{minimumFractionDigits:decimals,maximumFractionDigits:decimals})}${currency?` ${currency}`:""}`;
}

function signedMoney(value:number|null,currency:string):string{
  if(value===null) return "—";
  const sign=value>0?"+":value<0?"-":"";
  return `${sign}${Math.abs(value).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}${currency?` ${currency}`:""}`;
}

function eventTone(type:string):string{
  if([
    "notification_trade_close_failed",
    "notification_trade_close_unconfirmed",
    "notification_protection_failed",
    "notification_protection_unconfirmed",
    "notification_close_all_unconfirmed",
    "notification_trade_execution_failed",
    "notification_emergency_stop",
  ].includes(type)) return colors.red;
  if(type==="notification_trade_execution_blocked") return colors.amber;
  if(type==="notification_trade_opened"||type==="notification_position_protected"||type==="notification_close_all_confirmed") return colors.green;
  if(type==="notification_trade_closed"||type==="notification_trade_partially_closed") return colors.cyan;
  return colors.blue;
}

function eventLabel(type:string):string{
  const labels:Record<string,string>={
    notification_signal:"SIGNAL",
    notification_trade_opened:"POSITION OPENED",
    notification_trade_closed:"POSITION CLOSED",
    notification_trade_partially_closed:"PARTIAL CLOSE",
    notification_trade_close_failed:"CLOSE FAILED",
    notification_trade_close_unconfirmed:"CLOSE UNCONFIRMED",
    notification_position_protected:"PROTECTION SET",
    notification_protection_failed:"PROTECTION FAILED",
    notification_protection_unconfirmed:"PROTECTION UNCONFIRMED",
    notification_trade_execution_failed:"EXECUTION FAILED",
    notification_trade_execution_blocked:"ENTRY BLOCKED",
    notification_trade_approval_needed:"APPROVAL NEEDED",
    notification_emergency_stop:"EMERGENCY STOP",
    notification_close_all_confirmed:"CLOSE ALL CONFIRMED",
    notification_close_all_unconfirmed:"CLOSE ALL REVIEW",
    notification_test:"PUSH TEST",
  };
  return labels[type]??"EVENT";
}

function eventBody(event:any):string{
  const payload=event?.payload||{};
  if(event.type==="notification_signal") return `${payload.symbol||"Market"} · ${payload.action||"signal"} · score ${payload.score??"—"} · entry ${payload.entry??"—"}`;
  if(event.type==="notification_trade_opened") return `${payload.symbol||"Market"} · ${payload.side||"trade"} @ ${payload.entry??"—"}`;
  if(event.type==="notification_trade_execution_blocked") return `${payload.symbol||"Market"} · ${String(payload.reason||"blocked by safety checks").slice(0,140)}`;
  if(event.type==="notification_emergency_stop") return String(payload.message||"New trading disabled.");
  if(typeof payload.message==="string") return payload.message.slice(0,140);
  if(payload.position_id) return `Position #${payload.position_id} · ${payload.status||payload.result?.status||"check broker"}`;
  return "Trading event recorded";
}

/** Re-renders on its own once a second; keeps the console itself static. */
function SyncAge({at}:{at:number|null}){
  const now=useNow(1000);
  return <Stat label="SYNC" value={formatAge(at===null?null:Math.max(0,now-at))} sub="engine poll"/>;
}

export default function Bot(){
 const [engine,setEngine]=useState<any>(null);
 const [ai,setAi]=useState<any>(null);
 const [snapshot,setSnapshot]=useState<any>(null);
 const [account,setAccount]=useState<any>(null);
 const [journal,setJournal]=useState<any>(null);
 const [events,setEvents]=useState<any[]>([]);
 const [engineError,setEngineError]=useState("");
 const [feedError,setFeedError]=useState("");
 const [lastSyncAt,setLastSyncAt]=useState<number|null>(null);

 const [savingAi,setSavingAi]=useState(false);
 const [actionBusy,setActionBusy]=useState(false);
 const [emergencyBusy,setEmergencyBusy]=useState(false);
 const [closeAllBusy,setCloseAllBusy]=useState(false);
 const [savingRisk,setSavingRisk]=useState(false);

 const [riskDraft,setRiskDraft]=useState<RiskDraft|null>(null);
 const [minScoreDraft,setMinScoreDraft]=useState<number|null>(null);

 const screenMounted=useRef(false);
 const loadInFlight=useRef(false);
 const loadQueued=useRef(false);

 const load=async()=>{
  if(loadInFlight.current){loadQueued.current=true;return;}
  loadInFlight.current=true;
  try{
   const results=await Promise.allSettled([
    api.bot(),
    api.aiApproval(),
    api.ctraderAccount(),
    api.account(),
    api.journalStats(),
   ]);
   if(!screenMounted.current)return;

   const [botResult,approvalResult,brokerResult,accountResult,journalResult]=results;

   if(botResult.status==="fulfilled"){
    setEngine(botResult.value);
    setEngineError("");
   }else{
    setEngineError(String((botResult.reason as any)?.message||"Engine status could not be refreshed."));
   }

   if(approvalResult.status==="fulfilled") setAi(approvalResult.value);
   else setAi((current:any)=>current??{enabled:false,min_score:80});

   // A missing/unselected cTrader account is an expected pre-setup state (409)
   // and must not be shown as a failure; everything else is surfaced.
   if(brokerResult.status==="fulfilled"){
    setSnapshot(brokerResult.value);
   }else{
    const status=apiErrorStatus(brokerResult.reason);
    if(status===409||status===503) setSnapshot(null);
   }

   if(accountResult.status==="fulfilled") setAccount(accountResult.value);
   else if(apiErrorStatus(accountResult.reason)===409||apiErrorStatus(accountResult.reason)===503) setAccount(null);

   if(journalResult.status==="fulfilled") setJournal(journalResult.value);

   setLastSyncAt(Date.now());
  }finally{
   loadInFlight.current=false;
   if(screenMounted.current&&loadQueued.current){loadQueued.current=false;void load();}
  }
 };

 const loadFeed=async()=>{
  try{
   const result:any=await api.notificationEvents();
   if(!screenMounted.current)return;
   setEvents(Array.isArray(result?.events)?result.events.slice(0,8):[]);
   setFeedError("");
  }catch(error:any){
   if(screenMounted.current) setFeedError(String(error?.message||"Activity feed unavailable."));
  }
 };

 useEffect(()=>{
  screenMounted.current=true;
  void load();
  void loadFeed();
  const engineTimer=setInterval(()=>{void load()},20000);
  const feedTimer=setInterval(()=>{void loadFeed()},30000);
  const sub=AppState.addEventListener("change",state=>{
   if(state==="active"){void load();void loadFeed();}
  });
  return()=>{
   screenMounted.current=false;
   loadQueued.current=false;
   clearInterval(engineTimer);
   clearInterval(feedTimer);
   sub.remove();
  };
 },[]);

 // Seed the editable risk draft once the engine state is first available.
 useEffect(()=>{
  if(!engine||riskDraft) return;
  setRiskDraft({
   risk:num(engine.risk_per_trade)??0.5,
   daily:num(engine.daily_loss_limit)??2,
   maxOpen:num(engine.max_open_trades)??3,
   maxDd:num(engine.max_drawdown)??5,
  });
 },[engine,riskDraft]);

 useEffect(()=>{
  if(!ai) return;
  setMinScoreDraft(current=>current??(num(ai.min_score)??80));
 },[ai]);

 const action=async(fn:()=>Promise<any>)=>{
  if(actionBusy)return;
  setActionBusy(true);
  try{
   const result=await fn();
   if(screenMounted.current&&result&&typeof result==="object")setEngine((current:any)=>({...current,...result}));
  }catch(e:any){
   if(screenMounted.current)Alert.alert("Autopilot",e?.message||"Could not update the trading engine.");
  }finally{
   if(screenMounted.current)setActionBusy(false);
  }
 };

 async function toggleEngine(){
  if(!engine) return;
  if(engine.emergency_stopped){
   Alert.alert(
    "Reset emergency protection?",
    "This clears the emergency latch and leaves the bot stopped. Starting the engine is a separate, deliberate action afterwards.",
    [{text:"Cancel",style:"cancel"},{text:"RESET LATCH",onPress:()=>action(api.resetEmergency)}]
   );
   return;
  }
  if(engine.running){
   Alert.alert(
    "Stop the bot?",
    "TradeGuard stops scanning for new setups and no further orders are queued. Existing cTrader positions stay open and keep their broker-side stop-loss and take-profit.",
    [{text:"Cancel",style:"cancel"},{text:"STOP BOT",style:"destructive",onPress:()=>action(api.stopBot)}]
   );
   return;
  }
  await action(api.startBot);
 }

 async function emergencyStopNow(){
  // Emergency stop must remain usable even while a routine command is pending.
  if(emergencyBusy)return;
  setEmergencyBusy(true);
  try{
   const result=await api.emergencyStop();
   if(screenMounted.current){
    if(result&&typeof result==="object")setEngine((current:any)=>({...current,...((result as any).state??result)}));
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
     {text:"ENABLE",onPress:()=>saveAi(true,minScoreDraft??num(ai.min_score)??80)}
    ]
   );
  }else saveAi(false,minScoreDraft??num(ai.min_score)??80);
 }

 async function saveAi(enabled:boolean,minScore:number){
  setSavingAi(true);
  try{
   const result=await api.updateAiApproval({enabled,min_score:Math.max(70,Math.min(100,minScore))});
   if(screenMounted.current)setAi(result);
  }catch(e:any){
   if(screenMounted.current)Alert.alert("AI Approval",e?.message||"Could not update AI approval.");
  }finally{if(screenMounted.current)setSavingAi(false)}
 }

 // ---------------------------------------------------------------- derived ---
 const running=!!engine?.running;
 const halted=!!engine?.emergency_stopped;
 const brokerConnected=!!snapshot?.connected;
 const snapshotAt=snapshot?.updated_at?new Date(snapshot.updated_at):null;
 const snapshotAgeMs=snapshotAt&&Number.isFinite(snapshotAt.getTime())?Date.now()-snapshotAt.getTime():null;
 const snapshotStale=snapshotAgeMs===null||!Number.isFinite(snapshotAgeMs)||snapshotAgeMs<0||snapshotAgeMs>45000;

 const currency=String(snapshot?.currency||account?.currency||"").trim();
 const equity=brokerConnected&&!snapshotStale?num(snapshot?.equity):null;
 const balance=brokerConnected&&!snapshotStale?num(snapshot?.balance):null;
 const unrealized=brokerConnected&&!snapshotStale?num(snapshot?.unrealized_pnl):null;
 const dayPl=brokerConnected&&!snapshotStale?num(snapshot?.today_pl):null;
 const drawdown=brokerConnected&&!snapshotStale?num(snapshot?.drawdown):null;
 const openPositions=brokerConnected&&!snapshotStale?num(snapshot?.positions_count):null;

 const maxOpenTrades=num(engine?.max_open_trades)??num(account?.bot?.max_open_trades);
 const riskPerTrade=num(engine?.risk_per_trade);
 const dailyLimit=num(engine?.daily_loss_limit);
 const maxDrawdown=num(engine?.max_drawdown);

 const dayLossPct=dayPl!==null&&balance!==null&&balance>0&&dayPl<0?Math.abs(dayPl)/balance*100:dayPl!==null?0:null;

 const journalEntries=num(journal?.entries);
 const wins=num(journal?.wins);
 const losses=num(journal?.losses);
 const winRate=num(journal?.win_rate);
 const totalR=num(journal?.total_r);
 const totalPnl=num(journal?.total_pnl);

 const modeLabel=engine?.mode==="semi_auto"?"SEMI-AUTO":engine?.mode==="full_auto"?"FULL AUTO":"SIGNALS ONLY";
 const stateTone=halted?colors.red:running?colors.green:colors.amber;
 const stateLabel=halted?"HALTED":running?"MONITORING":"IDLE";

 const planSummary=briefRiskSummary();

 function briefRiskSummary(){
  const r=num(engine?.risk_per_trade),d=num(engine?.daily_loss_limit),m=num(engine?.max_open_trades),dd=num(engine?.max_drawdown);
  return `${r??"—"}% risk/trade · ${d??"—"}% daily loss · ${m??"—"} max positions · ${dd??"—"}% max drawdown`;
 }

 const riskDirty=!!riskDraft&&!!engine&&(
  Math.abs((num(engine.risk_per_trade)??0)-riskDraft.risk)>1e-9||
  Math.abs((num(engine.daily_loss_limit)??0)-riskDraft.daily)>1e-9||
  Math.abs((num(engine.max_open_trades)??0)-riskDraft.maxOpen)>1e-9||
  Math.abs((num(engine.max_drawdown)??0)-riskDraft.maxDd)>1e-9
 );
 const aiDirty=!!ai&&minScoreDraft!==null&&Math.abs((num(ai.min_score)??80)-minScoreDraft)>=0.5;

 async function applyRisk(){
  if(!riskDraft||!riskDirty||savingRisk) return;
  const next:RiskDraft={
   risk:Math.min(5,Math.max(0.1,riskDraft.risk)),
   daily:Math.min(20,Math.max(0.5,riskDraft.daily)),
   maxOpen:Math.min(20,Math.max(1,Math.round(riskDraft.maxOpen))),
   maxDd:Math.min(50,Math.max(1,riskDraft.maxDd)),
  };
  Alert.alert(
   "Apply new risk limits?",
   `${next.risk}% risk per trade · ${next.daily}% daily loss limit · ${next.maxOpen} max open positions · ${next.maxDd}% max drawdown.\n\nThe server enforces these before any order is queued.`,
   [
    {text:"Cancel",style:"cancel"},
    {text:"APPLY",onPress:async()=>{
     setSavingRisk(true);
     try{
      await api.updateRisk({
       risk_per_trade:next.risk,
       daily_loss_limit:next.daily,
       max_open_trades:next.maxOpen,
       max_drawdown:next.maxDd,
      });
      if(screenMounted.current)setRiskDraft(next);
      await load();
      if(screenMounted.current)Alert.alert("Risk limits updated","The new protection envelope is active and every future risk decision uses it.");
     }catch(e:any){
      if(screenMounted.current)Alert.alert("Risk limits",e?.message||"Could not update the risk envelope.");
     }finally{
      if(screenMounted.current)setSavingRisk(false);
     }
    }}
   ]
  );
 }

 async function applyAiScore(){
  if(!ai||minScoreDraft===null||!aiDirty||savingAi) return;
  await saveAi(!!ai.enabled,minScoreDraft);
 }

 // ------------------------------------------------------------------ render ---
 if(!engine){
  return <View style={s.offlineScreen}>
   <View style={s.offlineIcon}><Ionicons name="cloud-offline-outline" size={30} color={colors.amber}/></View>
   <Text style={s.offlineTitle}>ENGINE STATUS UNAVAILABLE</Text>
   <Text style={s.offlineCopy}>{engineError||"TradeGuard could not load the current bot state."} You can still send Stop or Emergency Stop; verify the outcome in Alerts and cTrader.</Text>
   <Pressable disabled={actionBusy} style={[s.offlineSecondary,actionBusy&&{opacity:0.6}]} onPress={()=>action(api.stopBot)}>
    <Text style={s.offlineSecondaryText}>{actionBusy?"SENDING STOP REQUEST…":"STOP BOT"}</Text>
   </Pressable>
   <Pressable disabled={emergencyBusy} style={[s.emergencyButton,emergencyBusy&&{opacity:0.65}]} onPress={emergencyStopNow}>
    <Ionicons name="hand-left-outline" size={16} color={colors.white}/>
    <Text style={s.emergencyText}>{emergencyBusy?"SENDING EMERGENCY STOP…":"EMERGENCY STOP"}</Text>
   </Pressable>
   <Pressable disabled={closeAllBusy} style={[s.emergencyButton,closeAllBusy&&{opacity:0.6}]} onPress={emergencyCloseAll}>
    <Ionicons name="close-circle-outline" size={16} color={colors.white}/>
    <Text style={s.emergencyText}>{closeAllBusy?"VERIFYING CLOSE ALL…":"CLOSE ALL POSITIONS"}</Text>
   </Pressable>
   <Pressable onPress={()=>void load()}><Text style={s.retry}>RETRY CONNECTION</Text></Pressable>
  </View>;
 }

 return <View style={s.screen}>
  <ScrollView contentContainerStyle={s.content} showsVerticalScrollIndicator={false}>

   {/* Header ----------------------------------------------------------------- */}
   <View style={s.header}>
    <View style={{flex:1}}>
     <Text style={s.eyebrow}>TRADEGUARD / AUTOPILOT</Text>
     <Text style={s.title}>Bot Console</Text>
     <Text style={s.sub}>Cloud strategy engine · server-enforced risk envelope</Text>
    </View>
    <View style={[s.statusChip,{borderColor:stateTone+"66",backgroundColor:stateTone+"12"}]}>
     <Pulse color={stateTone} active={running}/>
     <Text style={[s.statusText,{color:stateTone}]}>{stateLabel}</Text>
    </View>
   </View>

   {/* Engine hero ----------------------------------------------------------- */}
   <PanelCard glow={running&&!halted}>
    <View style={s.heroTop}>
     <View style={{flex:1}}>
      <Text style={s.heroLabel}>ENGINE STATE</Text>
      <View style={s.heroStateRow}>
       <Text style={[s.heroState,{color:stateTone}]}>{stateLabel}</Text>
       <Chip label={modeLabel} color={colors.blue}/>
      </View>
      <Text style={s.heroMeta}>
       {halted?"Emergency latch active — new entries blocked until reset":running?"Scanning markets for qualifying setups":"Stopped — no scanning, no new orders"}
      </Text>
     </View>
     <View style={[s.guardBadge,{borderColor:colors.borderGlow}]}>
      <Ionicons name="shield-checkmark" size={16} color={colors.green}/>
      <Text style={s.guardText}>RISK{"\n"}GUARD</Text>
     </View>
    </View>

    <View style={s.heroDivider}/>

    <View style={s.heroStats}>
     <SyncAge at={lastSyncAt}/>
     <Stat
      label="BROKER"
      value={brokerConnected?(snapshotStale?"STALE":"LIVE"):"OFFLINE"}
      tone={brokerConnected?(snapshotStale?"amber":"green"):"red"}
      sub={brokerConnected?`${String(snapshot?.environment||"").toUpperCase()} · ${snapshot?.account_id??"—"}`:"no account"}
     />
     <Stat
      label="AI APPROVAL"
      value={ai?.enabled?"ON":"OFF"}
      tone={ai?.enabled?"green":"default"}
      sub={ai?.enabled?`≥ ${num(ai.min_score)??"—"} score`:"manual only"}
     />
    </View>

    {engineError?<Text style={s.inlineWarning}>{engineError} Showing the last successful snapshot.</Text>:null}
   </PanelCard>

   {/* Execution lock strip --------------------------------------------------- */}
   <View style={s.lockStrip}>
    <Ionicons name="lock-closed" size={14} color={colors.amber}/>
    <View style={{flex:1}}>
     <Text style={s.lockTitle}>ORDER ROUTING LOCKED</Text>
     <Text style={s.lockCopy}>No automated entries reach cTrader until broker-verified volume sizing exists. Monitoring and manual closes stay available.</Text>
    </View>
   </View>

   {/* Account tape ----------------------------------------------------------- */}
   <SectionTitle label="ACCOUNT TAPE" right={brokerConnected?(snapshotStale?"SNAPSHOT STALE":"FRESH"):"NOT CONNECTED"}/>
   {brokerConnected?<>
    <View style={s.statRow}>
     <Stat label="EQUITY" value={money(equity,currency)} tone="default" emphasis/>
     <Stat label="BALANCE" value={money(balance,currency)}/>
    </View>
    <View style={s.statRow}>
     <Stat label="DAY P/L · UTC" value={signedMoney(dayPl,currency)} tone={dayPl===null?"default":dayPl>0?"green":dayPl<0?"red":"default"} sub="realized deals"/>
     <Stat label="OPEN P/L" value={signedMoney(unrealized,currency)} tone={unrealized===null?"default":unrealized>0?"green":unrealized<0?"red":"default"} sub="unrealized"/>
    </View>
    <View style={s.statRow}>
     <Stat label="OPEN POSITIONS" value={openPositions===null?"—":String(openPositions)} sub={maxOpenTrades!==null?`of ${maxOpenTrades} allowed`:"limit unknown"}/>
     <Stat label="DRAWDOWN" value={drawdown===null?"—":`${drawdown.toFixed(2)}%`} tone={drawdown===null?"default":drawdown>=((maxDrawdown??5)*0.7)?"amber":"green"} sub="from tracked peak"/>
    </View>
    {snapshotStale?<Text style={s.inlineWarning}>Broker snapshot is older than 45 seconds. Figures above are withheld until a fresh cTrader sync arrives.</Text>:null}
   </>:<PanelCard>
    <View style={s.emptyHead}>
     <Ionicons name="link-outline" size={18} color={colors.muted}/>
     <Text style={s.emptyTitle}>No broker account selected</Text>
    </View>
    <Text style={s.emptyCopy}>Connect and select a cTrader account in Settings to stream balance, equity, P/L and open positions into this console.</Text>
   </PanelCard>}

   {/* Risk envelope ---------------------------------------------------------- */}
   <SectionTitle label="RISK ENVELOPE" right="SERVER ENFORCED"/>
   <PanelCard>
    <Gauge label="OPEN POSITIONS" value={openPositions} limit={maxOpenTrades} format={value=>String(Math.round(value))} emptyLabel="awaiting broker"/>
    <Gauge label="DRAWDOWN" value={drawdown} limit={maxDrawdown} format={value=>`${value.toFixed(2)}%`} emptyLabel="awaiting broker"/>
    <Gauge label="DAILY LOSS" value={dayLossPct} limit={dailyLimit} format={value=>`${value.toFixed(2)}%`} emptyLabel="awaiting broker"/>
    <View style={s.riskFoot}>
     <Text style={s.riskFootLabel}>RISK / TRADE</Text>
     <Text style={s.riskFootValue}>{riskPerTrade===null?"—":`${riskPerTrade}%`}</Text>
    </View>
   </PanelCard>

   {/* AI approval ------------------------------------------------------------ */}
   <SectionTitle label="AI APPROVAL LAYER" right={ai?.enabled?"ARMED":"STANDBY"}/>
   <PanelCard>
    <View style={s.aiHeader}>
     <View style={{flex:1}}>
      <Text style={s.aiTitle}>{ai?.enabled?"Auto-approval armed":"Auto-approval off"}</Text>
      <Text style={s.aiCopy}>TradeGuard scores every confirmed setup and flags approvals above the threshold. It does not place orders while routing is locked.</Text>
     </View>
     <Toggle value={!!ai?.enabled} onChange={toggleAi} busy={savingAi}/>
    </View>
    <View style={s.aiScoreRow}>
     <View style={{flex:1}}>
      <Text style={s.rowLabel}>MINIMUM SIGNAL SCORE</Text>
      <Text style={s.rowHint}>70 – 100 · higher means fewer, stronger approvals</Text>
     </View>
     <Stepper
      value={minScoreDraft??80}
      step={1}
      min={70}
      max={100}
      disabled={savingAi}
      format={value=>String(Math.round(value))}
      onChange={next=>setMinScoreDraft(next)}
     />
    </View>
    {aiDirty?<Pressable disabled={savingAi} onPress={applyAiScore} style={[s.inlineButton,savingAi&&{opacity:0.6}]}>
     {savingAi?<ActivityIndicator size="small" color={colors.background}/>:<Text style={s.inlineButtonText}>SAVE THRESHOLD</Text>}
    </Pressable>:null}
   </PanelCard>

   {/* Execution mode --------------------------------------------------------- */}
   <SectionTitle label="EXECUTION MODE" right={running?"CHANGES APPLY LIVE":"ENGINE IDLE"}/>
   <PanelCard>
    <Segmented
     options={BOT_MODE_OPTIONS}
     value={(engine?.mode??null) as BotMode|null}
     disabledKeys={DISABLED_MODES}
     busy={actionBusy}
     onChange={mode=>{void action(()=>api.updateMode(mode));}}
    />
    <Text style={s.modeNote}>Semi-auto requires approval before a queued action. Full auto stays locked because broker-verified sizing is not available.</Text>
   </PanelCard>

   {/* Risk editor ------------------------------------------------------------ */}
   <SectionTitle label="PROTECTION PROFILE" right={riskDirty?"UNSAVED CHANGES":"CURRENT"}/>
   <PanelCard>
    <View style={s.editRow}>
     <View style={{flex:1}}>
      <Text style={s.rowLabel}>RISK PER TRADE</Text>
      <Text style={s.rowHint}>Account % risked on a single setup</Text>
     </View>
     <Stepper
      value={riskDraft?.risk??0.5}
      step={0.1}
      min={0.1}
      max={5}
      disabled={savingRisk}
      format={value=>`${value.toFixed(1)}%`}
      onChange={next=>setRiskDraft(current=>current?{...current,risk:next}:current)}
     />
    </View>
    <View style={s.editDivider}/>
    <View style={s.editRow}>
     <View style={{flex:1}}>
      <Text style={s.rowLabel}>DAILY LOSS LIMIT</Text>
      <Text style={s.rowHint}>Trading stops for the UTC day at this loss</Text>
     </View>
     <Stepper
      value={riskDraft?.daily??2}
      step={0.5}
      min={0.5}
      max={20}
      disabled={savingRisk}
      format={value=>`${value.toFixed(1)}%`}
      onChange={next=>setRiskDraft(current=>current?{...current,daily:next}:current)}
     />
    </View>
    <View style={s.editDivider}/>
    <View style={s.editRow}>
     <View style={{flex:1}}>
      <Text style={s.rowLabel}>MAX OPEN POSITIONS</Text>
      <Text style={s.rowHint}>Concurrent broker positions allowed</Text>
     </View>
     <Stepper
      value={riskDraft?.maxOpen??3}
      step={1}
      min={1}
      max={20}
      disabled={savingRisk}
      format={value=>String(Math.round(value))}
      onChange={next=>setRiskDraft(current=>current?{...current,maxOpen:next}:current)}
     />
    </View>
    <View style={s.editDivider}/>
    <View style={s.editRow}>
     <View style={{flex:1}}>
      <Text style={s.rowLabel}>MAX DRAWDOWN</Text>
      <Text style={s.rowHint}>Hard stop on tracked equity drawdown</Text>
     </View>
     <Stepper
      value={riskDraft?.maxDd??5}
      step={0.5}
      min={1}
      max={50}
      disabled={savingRisk}
      format={value=>`${value.toFixed(1)}%`}
      onChange={next=>setRiskDraft(current=>current?{...current,maxDd:next}:current)}
     />
    </View>
    {riskDirty?<Pressable disabled={savingRisk} onPress={applyRisk} style={[s.applyButton,savingRisk&&{opacity:0.6}]}>
     {savingRisk?<ActivityIndicator size="small" color={colors.background}/>:<Text style={s.applyText}>APPLY RISK LIMITS</Text>}
    </Pressable>:<Text style={s.currentPlan}>{planSummary}</Text>}
   </PanelCard>

   {/* Journal + feed --------------------------------------------------------- */}
   <SectionTitle label="ENGINE RECORD" right={journalEntries===null?"NO JOURNAL YET":`${journalEntries} JOURNAL ENTRIES`}/>
   <PanelCard>
    <View style={s.statRow}>
     <Stat
      label="WIN RATE"
      value={journalEntries!==null&&journalEntries>0&&winRate!==null?`${winRate.toFixed(1)}%`:"—"}
      sub={journalEntries===null?"no journal":`${wins??0}W / ${losses??0}L`}
     />
     <Stat
      label="TOTAL R"
      value={totalR===null?"—":`${totalR>0?"+":""}${totalR.toFixed(2)}R`}
      tone={totalR===null?"default":totalR>=0?"green":"red"}
      sub="risk multiple"
     />
     <Stat
      label="JOURNAL P/L"
      value={signedMoney(totalPnl,"")}
      tone={totalPnl===null?"default":totalPnl>=0?"green":"red"}
      sub="recorded"
     />
    </View>
   </PanelCard>

   <SectionTitle label="ACTIVITY FEED" right={feedError?"FEED ERROR":"LAST 8 EVENTS"}/>
   <PanelCard>
    {events.length===0
     ? <Text style={s.emptyCopy}>{feedError||"No engine events yet. Signals, blocked entries and execution results appear here as the bot scans."}</Text>
     : events.map((event:any,index:number)=><FeedRow
        key={String(event?.id??index)}
        title={eventLabel(String(event?.type))}
        body={eventBody(event)}
        meta={event?.created_at?new Date(event.created_at).toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"}):"—"}
        color={eventTone(String(event?.type))}
        last={index===events.length-1}
       />)}
   </PanelCard>

   <Text style={s.footnote}>
    TradeGuard never fabricates broker values. Missing balance, equity, P/L or currency stay blank until cTrader returns a verified snapshot.
   </Text>
  </ScrollView>

  {/* Control dock ------------------------------------------------------------ */}
  <View style={s.dock}>
   <Pressable
    disabled={actionBusy}
    onPress={()=>{void toggleEngine();}}
    style={[s.dockPrimary,running&&s.dockPrimaryStop,halted&&s.dockPrimaryHalted,actionBusy&&{opacity:0.65}]}>
    {actionBusy
     ? <ActivityIndicator size="small" color={running?colors.white:colors.background}/>
     : <Ionicons name={halted?"refresh":running?"pause":"play"} size={16} color={running||halted?colors.white:colors.background}/>}
    <Text style={[s.dockPrimaryText,(running||halted)&&{color:colors.white}]}>{actionBusy?"UPDATING…":halted?"RESET LATCH":running?"STOP BOT":"START BOT"}</Text>
   </Pressable>
   <Pressable disabled={emergencyBusy} onPress={()=>{void emergencyStopNow();}} style={[s.dockAction,emergencyBusy&&{opacity:0.6}]}>
    <Ionicons name="hand-left-outline" size={17} color={colors.red}/>
    <Text style={s.dockActionText}>{emergencyBusy?"SENDING":"STOP ALL"}</Text>
   </Pressable>
   <Pressable disabled={closeAllBusy} onPress={()=>{void emergencyCloseAll();}} style={[s.dockAction,closeAllBusy&&{opacity:0.6}]}>
    <Ionicons name="close-circle-outline" size={17} color={colors.amber}/>
    <Text style={s.dockActionText}>{closeAllBusy?"VERIFY":"CLOSE ALL"}</Text>
   </Pressable>
  </View>
 </View>;
}

const s=StyleSheet.create({
 screen:{flex:1,backgroundColor:colors.background},
 content:{padding:18,paddingTop:58,paddingBottom:190,gap:12},

 header:{flexDirection:"row",justifyContent:"space-between",alignItems:"flex-start",gap:10},
 eyebrow:{color:colors.green,fontSize:8,fontWeight:"900",letterSpacing:1.6},
 title:{color:colors.text,fontSize:29,fontWeight:"900",marginTop:3},
 sub:{color:colors.muted,fontSize:10,marginTop:4},
 statusChip:{flexDirection:"row",alignItems:"center",gap:6,paddingHorizontal:10,paddingVertical:7,borderRadius:radii.pill,borderWidth:1},
 statusText:{fontSize:8,fontWeight:"900",letterSpacing:.9},

 heroTop:{flexDirection:"row",alignItems:"flex-start",gap:12},
 heroLabel:{color:colors.muted,fontSize:8,fontWeight:"900",letterSpacing:1.2},
 heroStateRow:{flexDirection:"row",alignItems:"center",gap:8,marginTop:6},
 heroState:{fontSize:23,fontWeight:"900",letterSpacing:.4},
 heroMeta:{color:colors.muted,fontSize:10,lineHeight:15,marginTop:6},
 guardBadge:{alignItems:"center",gap:5,paddingHorizontal:10,paddingVertical:9,borderRadius:11,borderWidth:1,backgroundColor:"#08261a"},
 guardText:{color:colors.green,fontSize:7,fontWeight:"900",letterSpacing:.8,textAlign:"center"},
 heroDivider:{height:1,backgroundColor:colors.border,marginVertical:14},
 heroStats:{flexDirection:"row",gap:8},
 inlineWarning:{color:colors.amber,fontSize:10,lineHeight:14,marginTop:12},

 lockStrip:{flexDirection:"row",gap:10,alignItems:"flex-start",borderWidth:1,borderColor:colors.amber+"55",backgroundColor:"#141208",borderRadius:radii.md,padding:12},
 lockTitle:{color:colors.amber,fontSize:9,fontWeight:"900",letterSpacing:.8},
 lockCopy:{color:colors.muted,fontSize:10,lineHeight:14,marginTop:3},

 statRow:{flexDirection:"row",gap:8},
 riskFoot:{flexDirection:"row",justifyContent:"space-between",alignItems:"baseline",marginTop:14,paddingTop:12,borderTopWidth:1,borderTopColor:colors.border},
 riskFootLabel:{color:colors.muted,fontSize:8,fontWeight:"900",letterSpacing:.9},
 riskFootValue:{color:colors.text,fontSize:13,fontWeight:"900"},

 aiHeader:{flexDirection:"row",alignItems:"center",gap:14},
 aiTitle:{color:colors.text,fontSize:14,fontWeight:"900"},
 aiCopy:{color:colors.muted,fontSize:10,lineHeight:14,marginTop:4},
 aiScoreRow:{flexDirection:"row",alignItems:"center",gap:12,marginTop:16,paddingTop:14,borderTopWidth:1,borderTopColor:colors.border},
 rowLabel:{color:colors.textSoft,fontSize:9,fontWeight:"900",letterSpacing:.8},
 rowHint:{color:colors.muted2,fontSize:9,marginTop:3},
 inlineButton:{marginTop:12,height:40,borderRadius:10,backgroundColor:colors.green,alignItems:"center",justifyContent:"center"},
 inlineButtonText:{color:colors.background,fontSize:10,fontWeight:"900",letterSpacing:.8},
 modeNote:{color:colors.muted2,fontSize:9,lineHeight:13,marginTop:12},

 editRow:{flexDirection:"row",alignItems:"center",gap:12,paddingVertical:2},
 editDivider:{height:1,backgroundColor:colors.border,marginVertical:12},
 applyButton:{marginTop:16,height:46,borderRadius:12,backgroundColor:colors.green,alignItems:"center",justifyContent:"center"},
 applyText:{color:colors.background,fontSize:11,fontWeight:"900",letterSpacing:.9},
 currentPlan:{color:colors.muted2,fontSize:9,lineHeight:14,marginTop:14},

 emptyHead:{flexDirection:"row",alignItems:"center",gap:8},
 emptyTitle:{color:colors.text,fontSize:13,fontWeight:"900"},
 emptyCopy:{color:colors.muted,fontSize:11,lineHeight:16,marginTop:8},
 footnote:{color:colors.muted2,fontSize:9,lineHeight:13,textAlign:"center",marginTop:6},

 dock:{position:"absolute",left:14,right:14,bottom:94,flexDirection:"row",gap:8,alignItems:"center",backgroundColor:colors.surface,borderWidth:1,borderColor:colors.borderStrong,borderRadius:18,padding:8,...shadows.card},
 dockPrimary:{flex:1,height:50,borderRadius:13,backgroundColor:colors.green,flexDirection:"row",alignItems:"center",justifyContent:"center",gap:8},
 dockPrimaryStop:{backgroundColor:colors.redDeep,borderWidth:1,borderColor:colors.red+"77"},
 dockPrimaryHalted:{backgroundColor:"#7a2410",borderWidth:1,borderColor:colors.amber+"88"},
 dockPrimaryText:{color:colors.background,fontSize:12,fontWeight:"900",letterSpacing:.9},
 dockAction:{width:74,height:50,borderRadius:13,borderWidth:1,borderColor:colors.border,backgroundColor:colors.surface2,alignItems:"center",justifyContent:"center",gap:2},
 dockActionText:{color:colors.textSoft,fontSize:7,fontWeight:"900",letterSpacing:.5},

 offlineScreen:{flex:1,backgroundColor:colors.background,alignItems:"center",justifyContent:"center",padding:24,gap:14},
 offlineIcon:{width:64,height:64,borderRadius:20,borderWidth:1,borderColor:colors.borderStrong,backgroundColor:colors.surface2,alignItems:"center",justifyContent:"center"},
 offlineTitle:{color:colors.text,fontSize:17,fontWeight:"900",letterSpacing:.6},
 offlineCopy:{color:colors.muted,fontSize:12,lineHeight:18,textAlign:"center"},
 offlineSecondary:{height:50,width:"100%",borderRadius:14,borderWidth:1,borderColor:colors.borderStrong,backgroundColor:colors.surface2,alignItems:"center",justifyContent:"center"},
 offlineSecondaryText:{color:colors.textSoft,fontSize:11,fontWeight:"900",letterSpacing:.8},
 emergencyButton:{height:52,width:"100%",borderRadius:14,backgroundColor:"#a51f34",flexDirection:"row",gap:8,alignItems:"center",justifyContent:"center"},
 emergencyText:{color:colors.white,fontSize:12,fontWeight:"900",letterSpacing:.7},
 retry:{color:colors.green,fontSize:10,fontWeight:"900",letterSpacing:.8,marginTop:4},
});
