import {ScrollView,StyleSheet,Text,View,Pressable,ActivityIndicator} from "react-native";
import {Ionicons} from "@expo/vector-icons";
import {router} from "expo-router";
import {useEffect,useRef,useState} from "react";
import {AppState} from "react-native";
import {Panel} from "../../src/components/Panel";
import {colors,radii,shadows} from "../../src/theme";
import {api} from "../../src/api";
import {onCTraderAccountChanged} from "../../src/ctraderAccountEvents";

function Pill({label,ok=false,warn=false}:{label:string;ok?:boolean;warn?:boolean}){
  const color=ok?colors.green:warn?colors.amber:colors.red;
  return <View style={[s.pill,{borderColor:color+"55",backgroundColor:color+"12"}]}><View style={[s.pillDot,{backgroundColor:color}]}/><Text style={[s.pillText,{color}]}>{label}</Text></View>;
}
function Metric({label,value,accent}:{label:string;value:any;accent?:string}){
  return <View style={s.metric}><Text style={s.metricLabel}>{label}</Text><Text style={[s.metricValue,accent?{color:accent}:null]}>{value}</Text></View>;
}
function Gauge({value,max=100}:{value:number;max?:number}){
  const pct=Math.max(0,Math.min(1,value/max));
  return <View style={s.gauge}><View style={[s.gaugeFill,{width:`${pct*100}%`}]} /></View>;
}

export default function Home(){
  const [data,setData]=useState<any>(null),[broker,setBroker]=useState<any>(null),[cloud,setCloud]=useState<any>(null),[snapshot,setSnapshot]=useState<any>(null),[markets,setMarkets]=useState<any[]>([]),[notice,setNotice]=useState<any>(null),[err,setErr]=useState(""),[snapshotError,setSnapshotError]=useState(""),[marketError,setMarketError]=useState(""),[brokerError,setBrokerError]=useState(""),[cloudError,setCloudError]=useState("");
  const [safetyBusy,setSafetyBusy]=useState(false),[accountRefreshFailed,setAccountRefreshFailed]=useState(false);
  const accountLoadInFlight=useRef<Promise<boolean>|null>(null);
  const refreshInFlight=useRef(false);
  const refreshPending=useRef(false);
  const cloudIdentityRef=useRef<{id:string;environment:string}|null>(null);
  const snapshotIdentityRef=useRef<{id:string;environment:string}|null>(null);
  const identityKey=(value:any)=>({id:value?.account_id==null?"":String(value.account_id).trim(),environment:String(value?.environment??"").trim().toLowerCase()});
  const sameIdentity=(a:{id:string;environment:string}|null,b:{id:string;environment:string}|null)=>!!a&&!!b&&!!a.id&&!!b.id&&a.id===b.id&&a.environment===b.environment;
  const load=()=>{
    if(accountLoadInFlight.current)return accountLoadInFlight.current;
    const request=api.account().then((value:any)=>{setData(value);setErr("");setAccountRefreshFailed(false);return true}).catch(e=>{setAccountRefreshFailed(true);setErr(e?.message??"Network unavailable");return false}).finally(()=>{accountLoadInFlight.current=null});
    accountLoadInFlight.current=request;
    return request;
  };
  const runSafetyAction=async(fn:()=>Promise<any>,success:string)=>{if(safetyBusy)return;setSafetyBusy(true);setErr("");try{await fn();const refreshed=await load();setErr(refreshed?success:"Command completed, but account status could not be refreshed. Treat displayed account data as stale.");}catch(e:any){setErr(e?.message??"Safety command failed. Check the connection and try again.");}finally{setSafetyBusy(false);}};
  const loadMarkets=()=>api.markets().then((r:any)=>{setMarkets(Array.isArray(r)?r:[]);setMarketError("");}).catch((e:any)=>setMarketError(e?.message??"Market scan refresh failed; the last successful scan is retained."));
  const loadBroker=()=>api.broker().then((r:any)=>{setBroker(r);setBrokerError("");}).catch((e:any)=>setBrokerError(e?.message??"Broker summary refresh failed; the last successful values are retained."));
  const loadCloud=()=>api.ctraderConnection().then((r:any)=>{
    const nextIdentity=identityKey(r);
    const previousIdentity=cloudIdentityRef.current;
    const knownSnapshot=snapshotIdentityRef.current;
    const changed=!!previousIdentity&&!sameIdentity(previousIdentity,nextIdentity);
    const conflicts=!!knownSnapshot&&!!nextIdentity.id&&(knownSnapshot.id!==nextIdentity.id||knownSnapshot.environment!==nextIdentity.environment);
    cloudIdentityRef.current=nextIdentity;
    if(changed||conflicts){
      snapshotIdentityRef.current=null;
      setSnapshot(null);
      setSnapshotError("Selected cTrader account changed. Waiting for a fresh broker snapshot for the newly selected account.");
      setAccountRefreshFailed(true);
    }
    setCloud(r);setCloudError("");
  }).catch((e:any)=>setCloudError(e?.message??"cTrader connection refresh failed; the last successful status is retained."));
  const loadSnapshot=()=>api.ctraderAccountSnapshot().then((value:any)=>{
    const nextIdentity=identityKey(value);
    const selectedIdentity=cloudIdentityRef.current;
    if(selectedIdentity?.id&&(selectedIdentity.id!==nextIdentity.id||selectedIdentity.environment!==nextIdentity.environment)){
      snapshotIdentityRef.current=null;
      setSnapshot(null);
      setSnapshotError("Broker snapshot account does not match the currently selected cTrader account. Old account values are withheld.");
      setAccountRefreshFailed(true);
      return;
    }
    snapshotIdentityRef.current=nextIdentity;
    setSnapshot(value);setSnapshotError("");
  }).catch((e:any)=>{
    snapshotIdentityRef.current=null;
    setSnapshot(null);
    setSnapshotError(e?.message??"Unable to refresh the selected cTrader account snapshot. Previous account values are withheld until a fresh snapshot is available.");
    setAccountRefreshFailed(true);
  });
  const loadNotice=()=>api.notificationEvents().then((r:any)=>{if(r?.events?.[0])setNotice(r.events[0])}).catch(()=>{});
  const refreshAll=async()=>{
    if(refreshInFlight.current){refreshPending.current=true;return;}
    refreshInFlight.current=true;
    try{await Promise.allSettled([load(),loadMarkets(),loadBroker(),loadCloud(),loadSnapshot(),loadNotice()]);}
    finally{
      refreshInFlight.current=false;
      if(refreshPending.current){refreshPending.current=false;void refreshAll();}
    }
  };
  useEffect(()=>{
    let active=AppState.currentState==="active";
    let timer:ReturnType<typeof setInterval>|undefined;
    const refresh=()=>{if(active)void refreshAll();};
    const unsubscribe=onCTraderAccountChanged(()=>{
      cloudIdentityRef.current=null;
      snapshotIdentityRef.current=null;
      setCloud(null);setSnapshot(null);
      setCloudError("cTrader account changed. Verifying the newly selected account…");
      setSnapshotError("Waiting for a fresh snapshot for the newly selected cTrader account.");
      setAccountRefreshFailed(true);
      void refreshAll();
    });
    refresh();
    timer=setInterval(refresh,15000);
    const sub=AppState.addEventListener("change",state=>{
      active=state==="active";
      if(active)refresh();
    });
    return()=>{if(timer)clearInterval(timer);sub.remove();unsubscribe()};
  },[]);
  const running=!!data?.bot?.running, emergency=!!data?.bot?.emergency_stopped;
  const snapshotAccountId=snapshot?.account_id==null?"":String(snapshot.account_id).trim();
  const cloudAccountId=cloud?.account_id==null?"":String(cloud.account_id).trim();
  const snapshotEnvironment=String(snapshot?.environment??"").trim().toLowerCase();
  const cloudEnvironment=String(cloud?.environment??"").trim().toLowerCase();
  const accountIdentityConsistent=(!snapshotAccountId||!cloudAccountId||snapshotAccountId===cloudAccountId)&&(!snapshotEnvironment||!cloudEnvironment||snapshotEnvironment===cloudEnvironment);
  const accountSelected=!!(snapshotAccountId||cloudAccountId);
  const accountEnvironment=snapshotEnvironment||cloudEnvironment;
  const environmentIsDemo=accountEnvironment.includes("demo");
  const environmentIsLive=accountEnvironment.includes("live");
  const accountIdentityVerified=!!snapshotAccountId&&!!cloudAccountId&&snapshotAccountId===cloudAccountId&&snapshotEnvironment==="demo"&&cloudEnvironment==="demo"&&accountIdentityConsistent;
  const cloudConnected=!!cloud?.connected;
  const connected=cloudConnected&&accountIdentityConsistent&&environmentIsDemo;
  const heartbeatLabel=accountSelected?(environmentIsDemo?"DEMO ACCOUNT SELECTED":environmentIsLive?"LIVE ACCOUNT DETECTED · EXECUTION LOCKED":"ACCOUNT SELECTED · VERIFY ENVIRONMENT"):cloud?.authorized?"cTRADER AUTHORIZED · SELECT DEMO ACCOUNT":connected?"cTRADER CONNECTED · SELECT DEMO ACCOUNT":"WAITING FOR cTRADER";
  const dd=snapshot?.drawdown==null?Number.NaN:Number(snapshot.drawdown), maxDd=Number(data?.bot?.max_drawdown)||5, ddPct=Number.isFinite(dd)?Math.min(100,(dd/maxDd)*100):0;
  return <ScrollView style={s.screen} contentContainerStyle={s.c}>
    <View style={s.header}>
      <View><Text style={s.eyebrow}>TRADEGUARD  /  TRADING TERMINAL</Text><Text style={s.title}>Command Center</Text><Text style={s.sub}>Precision monitoring · cTrader Cloud</Text></View>
      <View style={s.logo}><Ionicons name="shield-checkmark" size={25} color={colors.green}/></View>
    </View>
    <View style={s.terminalBar}><View style={[s.terminalDot,{backgroundColor:connected?colors.green:colors.amber}]}/><Text style={[s.terminalText,{color:connected?colors.green:colors.amber}]}>{!accountIdentityConsistent?"ACCOUNT IDENTITY CONFLICT":connected?"CLOUD SESSION READY":"AWAITING VERIFIED CLOUD SESSION"}</Text><View style={s.terminalDivider}/><Ionicons name="lock-closed-outline" size={12} color={colors.muted}/><Text style={s.terminalLock}>{environmentIsLive?"LIVE ACCOUNT · EXECUTION LOCKED":accountIdentityVerified?"VERIFIED DEMO · SAFETY MODE":"ACCOUNT UNVERIFIED · EXECUTION LOCKED"}</Text></View>
    <View style={s.statusRow}><Pill label={connected?"cTRADER CLOUD ONLINE":"cTRADER CLOUD OFFLINE"} ok={connected}/><Pill label={running?"ENGINE RUNNING":"ENGINE IDLE"} ok={running}/>{emergency&&<Pill label="TRADING LOCKED" warn/>}</View>
    <Text style={[s.heartbeat,{color:connected?colors.green:colors.red}]}>● {heartbeatLabel} · {cloud?.environment?.toUpperCase()||"DEMO"}</Text>
    {err?<Panel><View style={s.inline}><Ionicons name="cloud-offline-outline" size={18} color={colors.red}/><Text style={s.error}>{err}</Text></View></Panel>:null}
    {data&&!data.account_metrics_available?<Panel><View style={s.inline}><Ionicons name="alert-circle-outline" size={18} color={colors.amber}/><Text style={s.error}>{data.account_metrics_message??"Verified cTrader risk metrics are unavailable. Risk-based approval and broker execution remain blocked."}</Text></View></Panel>:null}

    {snapshot&&!snapshotError&&snapshot.snapshot_status==="partial"?<Panel><View style={s.inline}><Ionicons name="alert-circle-outline" size={18} color={colors.amber}/><Text style={s.error}>The latest cTrader snapshot is PARTIAL. Some account metrics are unavailable; do not treat missing values as zero or fully verified.</Text></View></Panel>:null}
    {!accountIdentityConsistent?<Panel><View style={s.inline}><Ionicons name="warning-outline" size={18} color={colors.red}/><Text style={s.error}>ACCOUNT IDENTITY CONFLICT: the selected account ID or environment differs between the cTrader connection and account snapshot. Broker values are hidden and execution must remain locked. Refresh or reselect the demo account.</Text></View></Panel>:null}
    {accountSelected&&accountIdentityConsistent&&!accountIdentityVerified?<Panel><View style={s.inline}><Ionicons name="shield-outline" size={18} color={colors.amber}/><Text style={s.error}>Account identity is not fully verified. A matching selected demo account ID and demo environment are required before account values can be treated as current.</Text></View></Panel>:null}
    {snapshotError?<Panel><View style={s.inline}><Ionicons name="alert-circle-outline" size={18} color={colors.amber}/><Text style={s.error}>cTrader snapshot refresh failed: {snapshotError}{snapshot?" Last successful values remain visible and may be stale.":" No successful snapshot is available yet."}</Text></View></Panel>:null}
    <Panel>
      <View style={s.heroTop}><View style={{flex:1}}><Text style={s.label}>ACCOUNT BALANCE</Text><Text style={s.hero}>{!accountIdentityVerified||snapshotError||snapshot?.balance_status==="unavailable"||snapshot?.balance==null?"UNAVAILABLE":snapshot.balance}</Text><Text style={s.accountMeta}>{accountIdentityVerified?`Verified cTrader demo · Account ${snapshotAccountId}`:!accountIdentityConsistent?"Account identity conflict · values withheld":snapshot?.account_id?`Unverified snapshot · ${snapshot.environment??"Environment unknown"} · Account ${snapshot.account_id}`:cloud?.account_id?`Selected account · ${cloud.environment??"Environment unknown"} · Account ${cloud.account_id}`:cloud?.authorized?"cTrader authorized · select a demo account":"cTrader Cloud · not connected"}</Text></View><View style={s.liveRing}><Ionicons name="pulse" size={25} color={connected?colors.green:colors.red}/></View></View>
      <View style={s.divider}/><View style={s.metrics}><Metric label="OPEN POSITIONS" value={!accountIdentityVerified||snapshotError||snapshot?.positions_status==="unavailable"?"UNAVAILABLE":snapshot?.positions_count??"—"}/><Metric label="ACCOUNT ID" value={accountIdentityConsistent?(snapshotAccountId||cloudAccountId||"—"):"CONFLICT"}/><Metric label="SNAPSHOT" value={!accountIdentityConsistent?"CONFLICT":snapshot?(snapshotError?"STALE":snapshot.snapshot_status==="partial"?"PARTIAL":accountIdentityVerified?"VERIFIED":"UNVERIFIED"):"UNAVAILABLE"} accent={accountIdentityVerified&&!snapshotError&&snapshot?.snapshot_status==="complete"?colors.green:colors.amber}/></View>
    </Panel>

    <View style={s.sectionHead}><View><Text style={s.sectionTitle}>Risk Command</Text><Text style={s.sectionSub}>Live protection envelope</Text></View><Ionicons name="shield-half-outline" size={21} color={colors.green}/></View>
    <Panel>
      <View style={s.riskTop}><View><Text style={s.label}>RISK HEALTH</Text><Text style={[s.riskState,{color:emergency||environmentIsLive?colors.red:accountRefreshFailed||!data?.account_metrics_available||!accountIdentityVerified?colors.amber:colors.green}]}>{emergency?"EMERGENCY LOCK":environmentIsLive?"LIVE ACCOUNT LOCKED":!environmentIsDemo?"VERIFY ACCOUNT":accountRefreshFailed?"ACCOUNT DATA STALE":!data?.account_metrics_available?"METRICS UNVERIFIED":"RISK GATES ON"}</Text></View><Text style={s.riskPct}>{Number.isFinite(dd)&&data?.account_metrics_available&&!accountRefreshFailed?Math.round(ddPct)+"% USED":"BROKER DD UNVERIFIED"}</Text></View>
      {Number.isFinite(dd)&&data?.account_metrics_available&&!accountRefreshFailed?<Gauge value={ddPct}/>:<Text style={s.error}>Drawdown gauge unavailable until account metrics refresh successfully.</Text>}
      <View style={s.riskGrid}><Metric label="RISK / TRADE" value={(data?.bot?.risk_per_trade??0.5)+"%"}/><Metric label="DAILY LOSS" value={(data?.bot?.daily_loss_limit??2)+"%"}/><Metric label="OPEN TRADES" value={(data?.bot?.open_trades??0)+"/"+(data?.bot?.max_open_trades??3)}/><Metric label="MAX DD" value={maxDd+"%"}/></View>
    </Panel>

    <View style={s.sectionHead}><View><Text style={s.sectionTitle}>Market Radar</Text><Text style={s.sectionSub}>Highest-priority cloud signals</Text></View><Text style={[s.live,{color:marketError?colors.amber:colors.green}]}>● {marketError?"STALE":"CLOUD SCAN"}</Text></View>
    {(marketError||brokerError||cloudError)?<Panel><Text style={s.error}>Refresh warning: {[marketError,brokerError,cloudError].filter(Boolean).join(" · ")} Previously loaded values are retained and may be stale.</Text><Pressable style={s.secondary} onPress={()=>{void refreshAll();}}><Text style={s.secondaryText}>RETRY CLOUD DATA</Text><Ionicons name="refresh-outline" size={15} color={colors.green}/></Pressable></Panel>:null}
    <Panel>
      {markets.length===0?<View style={s.empty}><Text style={s.sub}>{marketError||"No successful market scan is available yet."}</Text><Pressable style={s.secondary} onPress={()=>{void refreshAll();}}><Text style={s.secondaryText}>RETRY MARKET SCAN</Text></Pressable></View>:markets.slice(0,6).map((m:any,i:number)=>{
        const buy=m.signal==="BUY",sell=m.signal==="SELL",c=buy?colors.green:sell?colors.red:colors.muted;
        return <View key={m.symbol} style={[s.marketRow,i>0&&s.rowBorder]}><View style={[s.marketIcon,{borderColor:c+"55"}]}><Ionicons name="pulse-outline" size={17} color={c}/></View><View style={{flex:1}}><Text style={s.symbol}>{m.symbol}</Text><Text style={s.marketSub}>{m.signal??"NO TRADE"} · cloud score</Text></View><View style={s.scoreBox}><Text style={[s.score,{color:c}]}>{m.score??0}</Text><Text style={[s.direction,{color:c}]}>{buy?"BUY":sell?"SELL":"WAIT"}</Text></View></View>
      })}<Pressable style={s.secondary} onPress={()=>router.push("/(tabs)/markets")}><Text style={s.secondaryText}>OPEN FULL MARKET TERMINAL</Text><Ionicons name="chevron-forward" size={15} color={colors.green}/></Pressable>
    </Panel>

    {notice?<Panel><View style={s.noticeHead}><Ionicons name="flash-outline" size={17} color={colors.green}/><Text style={s.noticeTitle}>LATEST EVENT</Text></View><Text style={s.noticeText}>{notice.payload?.symbol?`${notice.payload.symbol} · ${notice.payload.action??notice.payload.reason??""}`:notice.payload?.message??"Trading engine updated."}</Text></Panel>:null}

    {emergency?<Panel><View style={s.lock}><Ionicons name="lock-closed" size={18} color={colors.red}/><View style={{flex:1}}><Text style={s.lockTitle}>EMERGENCY STOP ACTIVE</Text><Text style={s.lockText}>New trading is blocked until protection is reset.</Text></View></View><Pressable disabled={safetyBusy} style={[s.reset,safetyBusy&&{opacity:0.55}]} onPress={()=>runSafetyAction(api.resetEmergency,"Protection reset.")}><Text style={s.resetText}>{safetyBusy?"PLEASE WAIT…":"RESET PROTECTION"}</Text></Pressable></Panel>:<Pressable disabled={safetyBusy} style={[s.emergency,safetyBusy&&{opacity:0.55}]} onPress={()=>runSafetyAction(api.emergencyStop,"Emergency stop activated.")}><Ionicons name="stop-circle-outline" size={19} color={colors.white}/><Text style={s.emergencyText}>{safetyBusy?"PLEASE WAIT…":"EMERGENCY STOP"}</Text></Pressable>}
    <Text style={s.footer}>TradeGuard Command Center · cTrader Cloud · demo safety mode</Text>
  </ScrollView>
}
const s=StyleSheet.create({
 screen:{flex:1,backgroundColor:colors.background},c:{padding:18,paddingTop:58,paddingBottom:112,gap:14},
 header:{flexDirection:"row",justifyContent:"space-between",alignItems:"center"},eyebrow:{color:colors.green,fontSize:8,fontWeight:"900",letterSpacing:1.8},title:{color:colors.text,fontSize:29,fontWeight:"900",marginTop:3},sub:{color:colors.muted,fontSize:10,marginTop:4},logo:{width:50,height:50,borderRadius:17,backgroundColor:"#08261a",borderWidth:1,borderColor:colors.borderStrong,alignItems:"center",justifyContent:"center",...shadows.glow},
 terminalBar:{flexDirection:"row",alignItems:"center",gap:7,borderWidth:1,borderColor:colors.border,backgroundColor:colors.surface2,borderRadius:11,paddingHorizontal:11,paddingVertical:10},terminalDot:{width:6,height:6,borderRadius:6},terminalText:{fontSize:7,fontWeight:"900",letterSpacing:.7},terminalDivider:{height:13,width:1,backgroundColor:colors.border,marginHorizontal:2},terminalLock:{color:colors.muted,fontSize:7,fontWeight:"900",letterSpacing:.6},
 statusRow:{flexDirection:"row",flexWrap:"wrap",gap:7},heartbeat:{fontSize:8,fontWeight:"900",letterSpacing:.7,marginTop:-7},pill:{flexDirection:"row",alignItems:"center",gap:6,paddingHorizontal:9,paddingVertical:7,borderRadius:radii.pill,borderWidth:1},pillDot:{width:6,height:6,borderRadius:6},pillText:{fontSize:8,fontWeight:"900",letterSpacing:.7},
 label:{color:colors.muted,fontSize:8,fontWeight:"900",letterSpacing:1.2},heroTop:{flexDirection:"row",alignItems:"center"},hero:{color:colors.text,fontSize:34,fontWeight:"900",marginTop:5},accountMeta:{color:colors.muted,fontSize:9,marginTop:5},liveRing:{width:50,height:50,borderRadius:25,backgroundColor:"#08261a",borderWidth:1,borderColor:colors.borderGlow,alignItems:"center",justifyContent:"center"},divider:{height:1,backgroundColor:colors.border,marginVertical:15},metrics:{flexDirection:"row",justifyContent:"space-between"},metric:{flex:1},metricLabel:{color:colors.muted2,fontSize:7,fontWeight:"900",letterSpacing:.8},metricValue:{color:colors.text,fontSize:13,fontWeight:"900",marginTop:5},
 sectionHead:{flexDirection:"row",justifyContent:"space-between",alignItems:"center",marginTop:2},sectionTitle:{color:colors.text,fontSize:16,fontWeight:"900"},sectionSub:{color:colors.muted,fontSize:10,marginTop:3},
 riskTop:{flexDirection:"row",justifyContent:"space-between",alignItems:"center"},riskState:{fontSize:20,fontWeight:"900",marginTop:4},riskPct:{color:colors.muted,fontSize:9,fontWeight:"900"},gauge:{height:7,borderRadius:8,backgroundColor:colors.surface3,overflow:"hidden",marginTop:14},gaugeFill:{height:7,backgroundColor:colors.green,borderRadius:8},riskGrid:{flexDirection:"row",flexWrap:"wrap",rowGap:15,marginTop:18},
 live:{color:colors.green,fontSize:8,fontWeight:"900",letterSpacing:1},marketRow:{flexDirection:"row",alignItems:"center",paddingVertical:12,gap:10},rowBorder:{borderTopWidth:1,borderTopColor:colors.border},marketIcon:{width:35,height:35,borderRadius:11,backgroundColor:"#08261a",borderWidth:1,alignItems:"center",justifyContent:"center"},symbol:{color:colors.text,fontSize:14,fontWeight:"900"},marketSub:{color:colors.muted,fontSize:9,marginTop:3},scoreBox:{alignItems:"flex-end"},score:{fontSize:17,fontWeight:"900"},direction:{fontSize:7,fontWeight:"900",marginTop:2},secondary:{height:42,borderRadius:11,borderWidth:1,borderColor:colors.border,backgroundColor:colors.surface2,flexDirection:"row",alignItems:"center",justifyContent:"center",gap:6,marginTop:7},secondaryText:{color:colors.green,fontSize:8,fontWeight:"900",letterSpacing:.6},
 noticeHead:{flexDirection:"row",alignItems:"center",gap:7},noticeTitle:{color:colors.green,fontSize:9,fontWeight:"900",letterSpacing:1},noticeText:{color:colors.text,fontSize:12,fontWeight:"800",marginTop:7},lock:{flexDirection:"row",alignItems:"center",gap:10},lockTitle:{color:colors.red,fontSize:11,fontWeight:"900"},lockText:{color:colors.muted,fontSize:10,marginTop:4},reset:{marginTop:13,borderWidth:1,borderColor:colors.green,borderRadius:10,padding:11,alignItems:"center"},resetText:{color:colors.green,fontSize:9,fontWeight:"900"},emergency:{height:50,borderRadius:14,backgroundColor:colors.redDeep,borderWidth:1,borderColor:"#c83a50",alignItems:"center",justifyContent:"center",flexDirection:"row",gap:8},emergencyText:{color:colors.white,fontSize:10,fontWeight:"900",letterSpacing:.7},inline:{flexDirection:"row",alignItems:"center",gap:8},error:{color:"#ffb5bf",fontSize:11,flex:1},empty:{alignItems:"center",gap:8,paddingVertical:16},footer:{color:colors.muted2,fontSize:8,textAlign:"center",marginTop:2}
});
