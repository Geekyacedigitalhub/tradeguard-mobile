import {ScrollView,StyleSheet,Text,View,Pressable,ActivityIndicator,Alert,Platform} from "react-native";
import {Ionicons} from "@expo/vector-icons";
import {router} from "expo-router";
import {useEffect,useRef,useState} from "react";
import {AppState} from "react-native";
import {Panel} from "../../src/components/Panel";
import {colors,radii,shadows} from "../../src/theme";
import {api} from "../../src/api";
import {useLiveTicks} from "../../src/live";
import {LiveChart,chartPriceText} from "../../src/components/LiveChart";
import {TickerTape,type TapeItem} from "../../src/components/TickerTape";
import {InstallPrompt} from "../../src/components/InstallPrompt";
import { useStage } from "../../src/useStage";

function Pill({label,ok=false,warn=false}:{label:string;ok?:boolean;warn?:boolean}){
  const color=ok?colors.green:warn?colors.amber:colors.red;
  return <View style={[s.pill,{borderColor:color+"55",backgroundColor:color+"12"}]}><View style={[s.pillDot,{backgroundColor:color}]} /><Text style={[s.pillText,{color}]}>{label}</Text></View>;
}
function Metric({label,value,accent}:{label:string;value:any;accent?:string}){
  return <View style={s.metric}><Text style={s.metricLabel}>{label}</Text><Text style={[s.metricValue,accent?{color:accent}:null]}>{value}</Text></View>;
}
function Gauge({value,max=100}:{value:number;max?:number}){
  const pct=Math.max(0,Math.min(1,value/max));
  return <View style={s.gauge}><View style={[s.gaugeFill,{width:`${pct*100}%`}]} /></View>;
}
function Clock(){
  const [now,setNow]=useState(()=>new Date());
  useEffect(()=>{const t=setInterval(()=>setNow(new Date()),1000);return()=>clearInterval(t)},[]);
  const p=(n:number)=>String(n).padStart(2,"0");
  return <Text style={s.clock}>{p(now.getUTCHours())}:{p(now.getUTCMinutes())}:{p(now.getUTCSeconds())} UTC</Text>;
}

const CHART_SYMBOLS=["EURUSD","XAUUSD","BTCUSD","NAS100","US30"];

export default function Home(){
  useStage("index");
  const [data,setData]=useState<any>(null),[detail,setDetail]=useState<any>(null),[markets,setMarkets]=useState<any[]>([]),[notice,setNotice]=useState<any>(null),[err,setErr]=useState(""),[closingAll,setClosingAll]=useState(false),[emergencyActionBusy,setEmergencyActionBusy]=useState(false),[engineBusy,setEngineBusy]=useState(false);
  const [livePrices,setLivePrices]=useState<Record<string,{price:number;base:number}>>({});
  const [chartSym,setChartSym]=useState("XAUUSD");
  const [chartPts,setChartPts]=useState<number[]>([]);
  const [chartBase,setChartBase]=useState<number|null>(null);
  const [equityPts,setEquityPts]=useState<number[]>([]);
  const accountRefreshInFlight=useRef(false);
  const refreshAfterCurrent=useRef(false);
  const screenMounted=useRef(true);
  const load=(forceAfterCurrent=false)=>{
    if(accountRefreshInFlight.current){
      if(forceAfterCurrent) refreshAfterCurrent.current=true;
      return Promise.resolve();
    }
    accountRefreshInFlight.current=true;
    return Promise.allSettled([api.account(),api.ctraderAccount()]).then(([accountResult,ctraderResult])=>{
    if(screenMounted.current&&accountResult.status==="fulfilled") setData(accountResult.value);
    if(screenMounted.current&&ctraderResult.status==="fulfilled") setDetail(ctraderResult.value);
    // Keep the last successful cTrader snapshot when a refresh fails; err marks it stale.
    const errors=[accountResult.status==="rejected"?accountResult.reason: null,ctraderResult.status==="rejected"?ctraderResult.reason:null].filter(Boolean);
    if(screenMounted.current) setErr(errors.length?String(errors[0]?.message??"Account refresh failed"):"");
    }).finally(()=>{
      accountRefreshInFlight.current=false;
      if(screenMounted.current&&refreshAfterCurrent.current){
        refreshAfterCurrent.current=false;
        void load();
      }
    });
  };
  const loadMarkets=()=>api.markets().then((r:any)=>{if(screenMounted.current)setMarkets(Array.isArray(r)?r:[])}).catch(()=>{/* Preserve the last successful market snapshot during transient network errors. */});
  const loadNotice=()=>api.notificationEvents().then((r:any)=>{if(screenMounted.current&&r?.events?.[0])setNotice(r.events[0])}).catch(()=>{});
  useEffect(()=>{
    screenMounted.current=true;
    const refresh=()=>{load();loadMarkets();loadNotice()};
    refresh();
    const timers=[setInterval(load,15000),setInterval(loadMarkets,30000),setInterval(loadNotice,30000)];
    const sub=AppState.addEventListener("change",state=>{if(state==="active"){load(true);loadMarkets();loadNotice()}});
    return()=>{screenMounted.current=false;refreshAfterCurrent.current=false;timers.forEach(clearInterval);sub.remove()};
  },[]);
  // Live broker ticks drive the tape, the chart and per-symbol change %.
  useLiveTicks((t)=>{
    if(!t.symbol)return;
    setLivePrices(prev=>{
      const ex=prev[t.symbol];
      const base=ex?.base??t.price;
      return {...prev,[t.symbol]:{price:t.price,base}};
    });
    if(t.symbol===chartSym){
      setChartPts(prev=>prev.length>=2?[...prev.slice(1),t.price]:prev);
    }
  });
  // Chart series: seed from candles, then stream live ticks into the tail.
  useEffect(()=>{
    let mounted=true;
    setChartPts([]);
    setChartBase(null);
    api.marketCandles(chartSym,"5m",80).then((r:any)=>{
      if(!mounted)return;
      const pts=(Array.isArray(r?.candles)?r.candles:[]).map((c:any)=>Number(c.close)).filter((v:number)=>Number.isFinite(v));
      if(pts.length>=2){setChartPts(pts);setChartBase(pts[0]);}
    }).catch(()=>{});
    return()=>{mounted=false};
  },[chartSym]);
  // Equity history for the sparkline.
  useEffect(()=>{
    let mounted=true;
    const loadHist=()=>api.equityHistory(48).then((r:any)=>{if(mounted)setEquityPts(Array.isArray(r?.points)?r.points.filter((v:any)=>Number.isFinite(v)):[])}).catch(()=>{});
    loadHist();
    const t=setInterval(loadHist,30000);
    return()=>{mounted=false;clearInterval(t)};
  },[]);
  const running=!!data?.bot?.running, emergency=!!data?.bot?.emergency_stopped;
  const connected=!!detail?.connected;
  const demoFeed=detail?.demo===true;
  const snapshotTime=detail?.updated_at?new Date(detail.updated_at):null;
  const snapshotAgeMs=snapshotTime?Date.now()-snapshotTime.getTime():null;
  const snapshotStale=snapshotAgeMs===null||!Number.isFinite(snapshotAgeMs)||snapshotAgeMs<0||snapshotAgeMs>45000;
  const heartbeatLabel=connected?(snapshotStale?"ACCOUNT SNAPSHOT STALE":snapshotAgeMs<10000?"BROKER SNAPSHOT FRESH":"SYNCED "+Math.round(snapshotAgeMs/1000)+"s AGO"):"WAITING FOR cTRADER";
  const brokerPositionsCount=connected&&!snapshotStale&&detail?.positions_count!==null&&detail?.positions_count!==undefined&&detail?.positions_count!==""&&Number.isFinite(Number(detail.positions_count))&&Number(detail.positions_count)>=0?Math.floor(Number(detail.positions_count)):null;
  const pnl=detail?.today_pl==null?NaN:Number(detail.today_pl),pnlColor=Number.isFinite(pnl)?(pnl>=0?colors.green:colors.red):colors.text;
  const dd=!snapshotStale&&detail?.drawdown!=null&&detail?.drawdown!==""?Number(detail.drawdown):null,maxDdRaw=data?.bot?.max_drawdown,maxDd=maxDdRaw==null||maxDdRaw===""?null:Number(maxDdRaw),ddPct=dd==null||!Number.isFinite(dd)||dd<0||maxDd==null||!Number.isFinite(maxDd)||maxDd<=0?null:Math.max(0,Math.min(100,(dd/maxDd)*100));
  const fmt=(v:any)=>v==null||v===""||!Number.isFinite(Number(v))?"—":Number(v).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
  const tape: TapeItem[]=markets.map(m=>{
    const live=livePrices[m.symbol];
    const price=live?live.price:Number(m.price);
    const change=live&&live.base>0?((live.price-live.base)/live.base)*100:Number(m.change_pct??0);
    return {symbol:m.symbol,price,change:Number.isFinite(change)?change:0};
  });
  const chartLive=livePrices[chartSym];
  const chartLast=chartPts.length?chartPts[chartPts.length-1]:(chartLive?chartLive.price:null);
  const chartChange=chartBase&&chartLast&&chartBase>0?((chartLast-chartBase)/chartBase)*100:null;
  const chartUp=chartChange==null?true:chartChange>=0;
  const eqUp=equityPts.length>=2?equityPts[equityPts.length-1]>=equityPts[0]:true;
  const quickEngine=async()=>{
    if(engineBusy)return;
    setEngineBusy(true);
    try{
      await (running?api.stopBot():api.startBot());
      await load(true);
    }catch(e:any){
      Alert.alert(running?"Stop failed":"Start failed",String(e?.message??"Could not update the engine. Check the connection and try again."));
    }finally{if(screenMounted.current)setEngineBusy(false)}
  };
  return <ScrollView style={s.screen} contentContainerStyle={s.c}>
    {Platform.OS==="web"?<InstallPrompt/>:null}
    <View style={s.header}><View style={{flex:1}}><View style={s.headerTop}><Text style={s.eyebrow}>TRADEGUARD / TRADING TERMINAL</Text><Clock/></View><Text style={s.title}>Command Center</Text><Text style={s.sub}>cTrader cloud · risk-gated execution</Text></View><View style={s.logo}><Ionicons name="shield-checkmark" size={25} color={colors.green}/></View></View>
    {tape.length>0?<TickerTape items={tape}/>:null}
    <View style={s.statusRow}><Pill label={connected?`cTRADER ${detail?.environment?.toUpperCase()||"CONNECTED"}`:"cTRADER OFFLINE"} ok={connected}/><Pill label={running?"STRATEGY ACTIVE":"STRATEGY IDLE"} ok={running}/><Pill label="ENTRIES BLOCKED" warn/>{demoFeed&&<Pill label="SIMULATED FEED" warn/>}{emergency&&<Pill label="TRADING LOCKED" warn/>}</View>
    <Text style={[s.heartbeat,{color:connected&&!snapshotStale?colors.green:colors.amber}]}>● {heartbeatLabel}  /  {brokerPositionsCount??"—"} BROKER POSITIONS</Text>
    {connected&&snapshotStale?<Panel><View style={s.inline}><Ionicons name="time-outline" size={18} color={colors.amber}/><Text style={[s.error,{color:colors.amber}]}>Last broker snapshot is older than 45 seconds or has no valid timestamp. Account figures are hidden and Close All is locked until a fresh cTrader snapshot arrives. Verify positions directly in cTrader.</Text></View></Panel>:null}
    {err?<Panel><View style={s.inline}><Ionicons name="cloud-offline-outline" size={18} color={colors.red}/><Text style={s.error}>{err}</Text></View></Panel>:null}
    <Panel>
      <View style={s.chartHead}>
        <View><Text style={s.label}>LIVE PRICE · 5M STREAM</Text><Text style={s.chartSym}>{chartSym}</Text></View>
        <View style={s.chartPriceBox}><Text style={[s.chartPrice,{color:chartUp?colors.green:colors.red}]}>{chartPriceText(chartLast)}</Text><Text style={[s.chartChange,{color:chartUp?colors.green:colors.red}]}>{chartChange==null?"—":(chartChange>=0?"+":"")+chartChange.toFixed(2)+"%"}</Text></View>
      </View>
      <View style={s.chips}>{CHART_SYMBOLS.map(sym=>{
        const m=markets.find(x=>x.symbol===sym);
        const active=sym===chartSym;
        const sig=m?.signal??"WAIT";
        const c=sig==="BUY"?colors.green:sig==="SELL"?colors.red:colors.muted;
        return <Pressable key={sym} style={[s.chip,active&&s.chipActive]} onPress={()=>setChartSym(sym)}><Text style={[s.chipText,{color:active?colors.green:colors.text}]}>{sym}</Text><View style={[s.chipDot,{backgroundColor:c}]} /></Pressable>;
      })}</View>
      <LiveChart values={chartPts} up={chartUp} height={138} gradientId="tgMainChart" />
      <Text style={s.chartFoot}>● STREAMING · last tick {chartPts.length?new Date().toLocaleTimeString(undefined,{hour12:false}):"—"} · cloud score {markets.find(m=>m.symbol===chartSym)?.score??"—"}</Text>
    </Panel>
    <Panel><View style={s.heroTop}><View style={{flex:1}}><Text style={s.label}>ACCOUNT EQUITY</Text><Text style={s.hero}>{connected&&!snapshotStale?fmt(detail?.equity)+" "+(detail?.currency||""):"—"}</Text><Text style={s.accountMeta}>{connected?`cTrader account ${detail?.account_id} · ${String(detail?.environment||"").toUpperCase()}`:"Connect a cTrader account in Settings"}</Text></View><View style={s.liveRing}><Ionicons name="pulse" size={25} color={connected?colors.green:colors.red}/></View></View>
      {equityPts.length>=2?<View style={s.sparkWrap}><LiveChart values={equityPts} up={eqUp} height={54} gradientId="tgEquityChart" /><Text style={s.sparkLabel}>EQUITY · LAST 48H</Text></View>:null}
      <View style={s.divider}/><View style={s.metrics}><Metric label="BALANCE" value={connected&&!snapshotStale?fmt(detail?.balance):"—"}/><Metric label="REALIZED P/L UTC" value={connected&&!snapshotStale?fmt(detail?.today_pl):"—"} accent={pnlColor}/><Metric label="TRACKED DD" value={connected&&!snapshotStale?fmt(detail?.drawdown)+"%":"—"}/></View>
    </Panel>
    <Panel><View style={s.engineHead}><View style={s.engineIcon}><Ionicons name="hardware-chip-outline" size={21} color={running?colors.green:colors.amber}/></View><View style={{flex:1}}><Text style={s.engineEyebrow}>STRATEGY ENGINE</Text><Text style={s.engineTitle}>{running?"Monitoring active":"Engine idle"}</Text><Text style={s.engineSub}>Cloud monitoring can run independently; new orders are disabled until broker risk sizing is verified.</Text></View></View><View style={s.engineBottom}><View style={s.executionLock}><Ionicons name="lock-closed" size={12} color={colors.amber}/><Text style={s.executionLockText}>ORDER EXECUTION DISABLED</Text></View><View style={s.engineActions}><Pressable disabled={engineBusy} style={[s.quickBtn,engineBusy&&{opacity:0.55}]} onPress={quickEngine}><Ionicons name={running?"stop-outline":"play-outline"} size={12} color={running?colors.red:colors.green}/><Text style={[s.quickBtnText,{color:running?colors.red:colors.green}]}>{engineBusy?"UPDATING":running?"STOP":"START"}</Text></Pressable><Pressable style={s.engineButton} onPress={()=>router.push("/(tabs)/bot")}><Text style={s.engineButtonText}>AUTOPILOT</Text><Ionicons name="arrow-forward" size={13} color={colors.green}/></Pressable></View></View></Panel>
    <View style={s.sectionHead}><View><Text style={s.sectionTitle}>Risk Command</Text><Text style={s.sectionSub}>Server-enforced protection envelope</Text></View><Ionicons name="shield-half-outline" size={21} color={colors.green}/></View>
    <Panel><View style={s.riskTop}><View><Text style={s.label}>RISK HEALTH</Text><Text style={[s.riskState,{color:emergency?colors.red:ddPct==null?colors.amber:colors.green}]}>{emergency?"LOCKED":ddPct==null?"METRICS PENDING":"TRACKING"}</Text></View><Text style={s.riskPct}>{ddPct==null?"N/A":Math.round(ddPct)+"% USED"}</Text></View>{ddPct==null?<Text style={s.accountMeta}>Broker drawdown is unavailable, so risk utilization cannot be calculated yet.</Text>:<><Gauge value={ddPct}/><Text style={s.accountMeta}>Drawdown is measured from TradeGuard’s first recorded equity peak; earlier account history is not included. Daily DD uses the first recorded equity snapshot of each UTC day, not a reconstructed midnight balance. Automated entries remain paused until broker-verified risk sizing is available.</Text></>}<View style={s.riskGrid}><Metric label="RISK / TRADE" value={(data?.bot?.risk_per_trade==null||data?.bot?.risk_per_trade===""||!Number.isFinite(Number(data.bot.risk_per_trade))?"—":Number(data.bot.risk_per_trade)+"%")}/><Metric label="DAILY DD" value={connected&&!snapshotStale&&detail?.daily_drawdown!==null&&detail?.daily_drawdown!==undefined&&detail?.daily_drawdown!==""&&Number.isFinite(Number(detail.daily_drawdown))?fmt(detail.daily_drawdown)+"%":"—"}/><Metric label="DAILY LIMIT" value={(data?.bot?.daily_loss_limit==null||data?.bot?.daily_loss_limit===""||!Number.isFinite(Number(data.bot.daily_loss_limit))?"—":Number(data.bot.daily_loss_limit)+"%")}/><Metric label="OPEN TRADES" value={(brokerPositionsCount===null?"—":brokerPositionsCount)+"/"+(data?.bot?.max_open_trades==null||data?.bot?.max_open_trades===""||!Number.isFinite(Number(data.bot.max_open_trades))?"—":data.bot.max_open_trades)}/><Metric label="MAX DD" value={maxDd===null?"—":maxDd+"%"} /></View></Panel>
    <View style={s.sectionHead}><View><Text style={s.sectionTitle}>Market Radar</Text><Text style={s.sectionSub}>Highest-priority cloud signals</Text></View><Text style={s.live}>● CLOUD</Text></View>
    <Panel>{markets.length===0?<View style={s.empty}><ActivityIndicator color={colors.green}/><Text style={s.sub}>Waiting for market data…</Text></View>:markets.slice(0,6).map((m:any,i:number)=>{const buy=m.signal==="BUY",sell=m.signal==="SELL",c=buy?colors.green:sell?colors.red:colors.muted;const live=livePrices[m.symbol];return <View key={m.symbol} style={[s.marketRow,i>0&&s.rowBorder]}><View style={[s.marketIcon,{borderColor:c+"55"}]}><Ionicons name="pulse-outline" size={17} color={c}/></View><View style={{flex:1}}><Text style={s.symbol}>{m.symbol}</Text><Text style={s.marketSub}>{m.signal??"NO TRADE"} · cloud score</Text></View><View style={s.scoreBox}><Text style={[s.score,{color:c}]}>{m.score==null||m.score===""||!Number.isFinite(Number(m.score))?"—":Number(m.score).toLocaleString(undefined,{maximumFractionDigits:1})}</Text><Text style={[s.direction,{color:c}]}>{live?chartPriceText(live.price):chartPriceText(m.price)}</Text><Text style={[s.direction,{color:c}]}>{buy?"BUY":sell?"SELL":"WAIT"}</Text></View></View>})}<Pressable style={s.secondary} onPress={()=>router.push("/(tabs)/markets")}><Text style={s.secondaryText}>OPEN FULL MARKET TERMINAL</Text><Ionicons name="chevron-forward" size={15} color={colors.green}/></Pressable></Panel>
    {notice?<Panel><View style={s.noticeHead}><Ionicons name="flash-outline" size={17} color={colors.green}/><Text style={s.noticeTitle}>LATEST EVENT</Text></View><Text style={s.noticeText}>{notice.payload?.symbol?`${notice.payload.symbol} · ${notice.payload.action??notice.payload.reason??""}`:notice.payload?.message??"Trading engine updated."}</Text></Panel>:null}
    {emergency?<Panel><View style={s.lock}><Ionicons name="lock-closed" size={18} color={colors.red}/><View style={{flex:1}}><Text style={s.lockTitle}>EMERGENCY STOP ACTIVE</Text><Text style={s.lockText}>New trading is blocked until protection is reset.</Text></View></View><Pressable disabled={emergencyActionBusy} style={[s.reset,emergencyActionBusy&&{opacity:0.55}]} onPress={async()=>{if(emergencyActionBusy)return;setEmergencyActionBusy(true);try{await api.resetEmergency();await load(true);Alert.alert("Protection reset","The server accepted the reset. Automated entries remain blocked pending verified broker risk sizing.");}catch(error:any){Alert.alert("Reset failed",String(error?.message??"Could not reset protection. Check the connection and server status."));}finally{if(screenMounted.current)setEmergencyActionBusy(false)}}}><Text style={s.resetText}>{emergencyActionBusy?"RESETTING…":"RESET PROTECTION"}</Text></Pressable></Panel>:<Pressable disabled={emergencyActionBusy} style={[s.emergency,emergencyActionBusy&&{opacity:0.55}]} onPress={async()=>{if(emergencyActionBusy)return;setEmergencyActionBusy(true);try{await api.emergencyStop();await load(true);Alert.alert("Emergency stop requested","The server accepted the emergency-stop request. Existing positions are not automatically closed; use Close All separately and verify cTrader.");}catch(error:any){Alert.alert("Emergency stop failed",String(error?.message??"Could not confirm the emergency-stop request. Check cTrader and the server immediately."));}finally{if(screenMounted.current)setEmergencyActionBusy(false)}}}><Ionicons name="stop-circle-outline" size={19} color={colors.white}/><Text style={s.emergencyText}>{emergencyActionBusy?"SENDING STOP…":"EMERGENCY STOP"}</Text></Pressable>}
    {connected&&Number(detail?.positions_count)>0?<Pressable disabled={closingAll||snapshotStale} style={[s.closeAll,(closingAll||snapshotStale)&&{opacity:0.55}]} onPress={()=>Alert.alert("Close all cTrader positions?","This sends a market-close request for every open position on the currently selected cTrader account. Market execution and slippage are controlled by the broker. Confirm only if you want to close them all.",[{text:"Cancel",style:"cancel"},{text:"CLOSE ALL",style:"destructive",onPress:async()=>{setClosingAll(true);try{const result:any=await api.closeAll();
const rawIds=Array.isArray(result?.command_ids)?result.command_ids:[result?.command_id];
const commandIds=rawIds.map((id:any)=>Number(id)).filter((id:number)=>Number.isInteger(id)&&id>0);
if(commandIds.length===0){Alert.alert(result?.position_count===0||result?.status==="no_open_positions"?"No open positions":"Close-all not confirmed",result?.position_count===0||result?.status==="no_open_positions"?"cTrader confirmed there were no open positions.":result?.message||"No valid command IDs were returned. Check cTrader before retrying.");await load(true);loadNotice();return;}
const statuses:any[]=await Promise.all(commandIds.map(async(commandId:number)=>{let status:any=null;for(let attempt=0;attempt<8;attempt++){try{status=await api.cTraderCommand(commandId)}catch{status=null}if(status&&(status.status==="completed"||status.status==="failed"))break;await new Promise(resolve=>setTimeout(resolve,1500));}return status;}));
const unfinished=statuses.filter((status:any)=>!status||(status.status!=="completed"&&status.status!=="failed")).length;
const perCommand:any[][]=statuses.map((status:any)=>Array.isArray(status?.result?.positions)?status.result.positions:status?.result&&typeof status.result==="object"&&Object.keys(status.result).length>0?[status.result]:[]);
const positions:Array<any>=perCommand.flat();
const closed=positions.filter(item=>item?.status==="confirmed_closed").length;
const reduced=positions.filter(item=>item?.status==="confirmed_reduced").length;
const unexpected=positions.filter(item=>item?.status==="changed_unexpectedly").length;
const failedPositions=positions.filter(item=>item?.status==="failed").length;
const workerFailed=statuses.filter((status:any,i:number)=>status?.status==="failed"&&(!perCommand[i].length||!perCommand[i].some(item=>item?.status==="failed"))).length;
const missingCompleted=statuses.filter((status:any,i:number)=>status?.status==="completed"&&perCommand[i].length===0).length;
const failed=failedPositions+workerFailed;
const unconfirmed=Math.max(0,unfinished+missingCompleted+positions.filter(item=>!["confirmed_closed","confirmed_reduced","changed_unexpectedly","failed"].includes(item?.status)).length);
Alert.alert("Close All result",`${closed} fully closed · ${reduced} partially reduced · ${failed} failed/worker errors · ${unexpected} unexpected changes · ${unconfirmed} unconfirmed. Verify remaining positions in cTrader before retrying.`);
await load(true);loadNotice();}catch(error:any){Alert.alert("Close All outcome unknown",`The request may have reached the cloud even though no result was received. Check cTrader and refresh positions before retrying. Details: ${String(error?.message??"request result unavailable")}`);await load(true);loadNotice()}finally{if(screenMounted.current)setClosingAll(false)}}}])}><Ionicons name="warning-outline" size={19} color={colors.white}/><Text style={s.closeAllText}>{closingAll?"QUEUEING CLOSE-ALL…":snapshotStale?"REFRESH REQUIRED":"CLOSE ALL OPEN POSITIONS"}</Text></Pressable>:null}
    <Text style={s.footer}>TradeGuard · cTrader cloud execution · safety-gated</Text>
  </ScrollView>;
}
const s=StyleSheet.create({
 screen:{flex:1,backgroundColor:colors.background},c:{padding:18,paddingTop:58,paddingBottom:112,gap:14},
 header:{flexDirection:"row",justifyContent:"space-between",alignItems:"center"},headerTop:{flexDirection:"row",alignItems:"center",gap:10},clock:{color:colors.muted,fontSize:8,fontWeight:"900",letterSpacing:1,backgroundColor:colors.surface,borderWidth:1,borderColor:colors.border,borderRadius:radii.pill,paddingHorizontal:8,paddingVertical:4},eyebrow:{color:colors.green,fontSize:8,fontWeight:"900",letterSpacing:1.8},title:{color:colors.text,fontSize:29,fontWeight:"900",marginTop:3},sub:{color:colors.muted,fontSize:10,marginTop:4},logo:{width:50,height:50,borderRadius:17,backgroundColor:"#08261a",borderWidth:1,borderColor:colors.borderStrong,alignItems:"center",justifyContent:"center",...shadows.glow},
 statusRow:{flexDirection:"row",flexWrap:"wrap",gap:7},heartbeat:{fontSize:8,fontWeight:"900",letterSpacing:.7,marginTop:-7},pill:{flexDirection:"row",alignItems:"center",gap:6,paddingHorizontal:9,paddingVertical:7,borderRadius:radii.pill,borderWidth:1},pillDot:{width:6,height:6,borderRadius:6},pillText:{fontSize:8,fontWeight:"900",letterSpacing:.7},
 label:{color:colors.muted,fontSize:8,fontWeight:"900",letterSpacing:1.2},
 chartHead:{flexDirection:"row",justifyContent:"space-between",alignItems:"flex-end"},chartSym:{color:colors.text,fontSize:21,fontWeight:"900",marginTop:4},chartPriceBox:{alignItems:"flex-end"},chartPrice:{color:colors.text,fontSize:20,fontWeight:"900"},chartChange:{fontSize:10,fontWeight:"900",marginTop:3},chips:{flexDirection:"row",flexWrap:"wrap",gap:6,marginTop:12},chip:{flexDirection:"row",alignItems:"center",gap:5,borderWidth:1,borderColor:colors.border,backgroundColor:colors.surface2,borderRadius:radii.pill,paddingHorizontal:10,paddingVertical:6},chipActive:{borderColor:colors.borderGlow,backgroundColor:"#08261a"},chipText:{fontSize:9,fontWeight:"900",letterSpacing:.5},chipDot:{width:5,height:5,borderRadius:3},chartFoot:{color:colors.muted2,fontSize:7,fontWeight:"900",letterSpacing:.7,marginTop:10},
 heroTop:{flexDirection:"row",alignItems:"center"},hero:{color:colors.text,fontSize:29,fontWeight:"900",marginTop:5},accountMeta:{color:colors.muted,fontSize:9,marginTop:5},liveRing:{width:50,height:50,borderRadius:25,backgroundColor:"#08261a",borderWidth:1,borderColor:colors.borderGlow,alignItems:"center",justifyContent:"center"},sparkWrap:{marginVertical:13,borderWidth:1,borderColor:colors.border,backgroundColor:colors.panel,borderRadius:10,padding:8},sparkLabel:{color:colors.muted2,fontSize:7,fontWeight:"900",letterSpacing:.8,marginTop:6},divider:{height:1,backgroundColor:colors.border,marginVertical:15},metrics:{flexDirection:"row",justifyContent:"space-between"},metric:{flex:1},metricLabel:{color:colors.muted2,fontSize:7,fontWeight:"900",letterSpacing:.8},metricValue:{color:colors.text,fontSize:13,fontWeight:"900",marginTop:5},
 engineHead:{flexDirection:"row",alignItems:"flex-start",gap:12},engineIcon:{width:42,height:42,borderRadius:11,backgroundColor:colors.surface3,borderWidth:1,borderColor:colors.borderStrong,alignItems:"center",justifyContent:"center"},engineEyebrow:{color:colors.muted,fontSize:8,fontWeight:"900",letterSpacing:1.3},engineTitle:{color:colors.text,fontSize:17,fontWeight:"900",marginTop:4},engineSub:{color:colors.muted,fontSize:10,lineHeight:15,marginTop:5},engineBottom:{flexDirection:"row",alignItems:"center",justifyContent:"space-between",gap:8,borderTopWidth:1,borderTopColor:colors.border,marginTop:14,paddingTop:12},executionLock:{flexDirection:"row",alignItems:"center",gap:5,flexShrink:1},executionLockText:{color:colors.amber,fontSize:8,fontWeight:"900",letterSpacing:.5},engineActions:{flexDirection:"row",alignItems:"center",gap:6},quickBtn:{flexDirection:"row",alignItems:"center",gap:5,borderWidth:1,borderColor:colors.borderStrong,backgroundColor:colors.surface2,borderRadius:8,paddingVertical:9,paddingHorizontal:10},quickBtnText:{fontSize:8,fontWeight:"900",letterSpacing:.7},engineButton:{flexDirection:"row",alignItems:"center",gap:6,borderWidth:1,borderColor:colors.borderStrong,backgroundColor:colors.surface2,borderRadius:8,paddingVertical:9,paddingHorizontal:10},engineButtonText:{color:colors.green,fontSize:8,fontWeight:"900",letterSpacing:.7},
 sectionHead:{flexDirection:"row",justifyContent:"space-between",alignItems:"center",marginTop:2},sectionTitle:{color:colors.text,fontSize:16,fontWeight:"900"},sectionSub:{color:colors.muted,fontSize:10,marginTop:3},
 riskTop:{flexDirection:"row",justifyContent:"space-between",alignItems:"center"},riskState:{fontSize:20,fontWeight:"900",marginTop:4},riskPct:{color:colors.muted,fontSize:9,fontWeight:"900"},gauge:{height:7,borderRadius:8,backgroundColor:colors.surface3,overflow:"hidden",marginTop:14},gaugeFill:{height:7,backgroundColor:colors.green,borderRadius:8},riskGrid:{flexDirection:"row",flexWrap:"wrap",rowGap:15,marginTop:18},
 live:{color:colors.green,fontSize:8,fontWeight:"900",letterSpacing:1},marketRow:{flexDirection:"row",alignItems:"center",paddingVertical:12,gap:10},rowBorder:{borderTopWidth:1,borderTopColor:colors.border},marketIcon:{width:35,height:35,borderRadius:11,backgroundColor:"#08261a",borderWidth:1,alignItems:"center",justifyContent:"center"},symbol:{color:colors.text,fontSize:14,fontWeight:"900"},marketSub:{color:colors.muted,fontSize:9,marginTop:3},scoreBox:{alignItems:"flex-end"},score:{fontSize:17,fontWeight:"900"},direction:{fontSize:7,fontWeight:"900",marginTop:2},secondary:{height:42,borderRadius:11,borderWidth:1,borderColor:colors.border,backgroundColor:colors.surface2,flexDirection:"row",alignItems:"center",justifyContent:"center",gap:6,marginTop:7},secondaryText:{color:colors.green,fontSize:8,fontWeight:"900",letterSpacing:.6},
 noticeHead:{flexDirection:"row",alignItems:"center",gap:7},noticeTitle:{color:colors.green,fontSize:9,fontWeight:"900",letterSpacing:1},noticeText:{color:colors.text,fontSize:12,fontWeight:"800",marginTop:7},lock:{flexDirection:"row",alignItems:"center",gap:10},lockTitle:{color:colors.red,fontSize:11,fontWeight:"900"},lockText:{color:colors.muted,fontSize:10,marginTop:4},reset:{marginTop:13,borderWidth:1,borderColor:colors.green,borderRadius:10,padding:11,alignItems:"center"},resetText:{color:colors.green,fontSize:9,fontWeight:"900"},closeAll:{minHeight:48,borderRadius:11,borderWidth:1,borderColor:colors.red+"88",backgroundColor:"#351313",flexDirection:"row",alignItems:"center",justifyContent:"center",gap:9,paddingHorizontal:14},closeAllText:{color:colors.white,fontSize:10,fontWeight:"900",letterSpacing:.7},emergency:{height:50,borderRadius:14,backgroundColor:colors.redDeep,borderWidth:1,borderColor:"#c83a50",alignItems:"center",justifyContent:"center",flexDirection:"row",gap:8},emergencyText:{color:colors.white,fontSize:10,fontWeight:"900",letterSpacing:.7},inline:{flexDirection:"row",alignItems:"center",gap:8},error:{color:"#ffb5bf",fontSize:11,flex:1},empty:{alignItems:"center",gap:8,paddingVertical:16},footer:{color:colors.muted2,fontSize:8,textAlign:"center",marginTop:2}
});
