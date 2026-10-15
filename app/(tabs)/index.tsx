import {ScrollView,StyleSheet,Text,View,Pressable,ActivityIndicator} from "react-native";
import {Ionicons} from "@expo/vector-icons";
import {router} from "expo-router";
import {useEffect,useState} from "react";
import {AppState} from "react-native";
import {Panel} from "../../src/components/Panel";
import {colors,radii,shadows} from "../../src/theme";
import {api} from "../../src/api";

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
  const [data,setData]=useState<any>(null),[broker,setBroker]=useState<any>(null),[cloud,setCloud]=useState<any>(null),[snapshot,setSnapshot]=useState<any>(null),[markets,setMarkets]=useState<any[]>([]),[notice,setNotice]=useState<any>(null),[err,setErr]=useState("");
  const load=()=>api.account().then(setData).catch(e=>setErr(e?.message??"Network unavailable"));
  const loadMarkets=()=>api.markets().then((r:any)=>setMarkets(Array.isArray(r)?r:[])).catch(()=>setMarkets([]));
  const loadBroker=()=>api.broker().then(setBroker).catch(()=>setBroker(null));
  const loadCloud=()=>api.ctraderConnection().then(setCloud).catch(()=>setCloud(null));
  const loadSnapshot=()=>api.ctraderAccountSnapshot().then(setSnapshot).catch(()=>setSnapshot(null));
  const loadNotice=()=>api.notificationEvents().then((r:any)=>{if(r?.events?.[0])setNotice(r.events[0])}).catch(()=>{});
  useEffect(()=>{load();loadMarkets();loadBroker();loadCloud();loadSnapshot();loadNotice();const a=setInterval(load,15000),m=setInterval(loadMarkets,30000),b=setInterval(loadBroker,15000),c=setInterval(loadCloud,10000),ss=setInterval(loadSnapshot,15000),n=setInterval(loadNotice,30000);const sub=AppState.addEventListener("change",x=>x==="active"&&(load(),loadMarkets(),loadBroker(),loadCloud(),loadSnapshot(),loadNotice()));return()=>{clearInterval(a);clearInterval(m);clearInterval(b);clearInterval(c);clearInterval(ss);clearInterval(n);sub.remove()}},[]);
  const running=!!data?.bot?.running, emergency=!!data?.bot?.emergency_stopped, connected=!!cloud?.connected;
  const heartbeatLabel=connected?"DEMO ACCOUNT SELECTED":"WAITING FOR cTRADER";
  const dd=snapshot?.drawdown==null?Number.NaN:Number(snapshot.drawdown), maxDd=Number(data?.bot?.max_drawdown)||5, ddPct=Number.isFinite(dd)?Math.min(100,(dd/maxDd)*100):0;
  return <ScrollView style={s.screen} contentContainerStyle={s.c}>
    <View style={s.header}>
      <View><Text style={s.eyebrow}>TRADEGUARD / COMMAND</Text><Text style={s.title}>Trading Master</Text><Text style={s.sub}>Broker execution locked. Risk gates active.</Text></View>
      <View style={s.logo}><Ionicons name="shield-checkmark" size={25} color={colors.green}/></View>
    </View>
    <View style={s.statusRow}><Pill label={connected?"cTRADER CLOUD ONLINE":"cTRADER CLOUD OFFLINE"} ok={connected}/><Pill label={running?"ENGINE RUNNING":"ENGINE IDLE"} ok={running}/>{emergency&&<Pill label="TRADING LOCKED" warn/>}</View>
    <Text style={[s.heartbeat,{color:connected?colors.green:colors.red}]}>● {heartbeatLabel} · {cloud?.environment?.toUpperCase()||"DEMO"}</Text>
    {err?<Panel><View style={s.inline}><Ionicons name="cloud-offline-outline" size={18} color={colors.red}/><Text style={s.error}>{err}</Text></View></Panel>:null}

    <Panel>
      <View style={s.heroTop}><View style={{flex:1}}><Text style={s.label}>BROKER BALANCE</Text><Text style={s.hero}>{snapshot?.balance??"—"}</Text><Text style={s.accountMeta}>{cloud?.account?"cTrader · "+cloud.account:"cTrader Cloud · Demo"}</Text></View><View style={s.liveRing}><Ionicons name="pulse" size={25} color={connected?colors.green:colors.red}/></View></View>
      <View style={s.divider}/><View style={s.metrics}><Metric label="OPEN POSITIONS" value={snapshot?.positions_count??"—"}/><Metric label="ACCOUNT ID" value={snapshot?.account_id??"—"}/><Metric label="SNAPSHOT" value={snapshot?"SYNCED":"UNAVAILABLE"} accent={snapshot?colors.green:colors.amber}/></View>
    </Panel>

    <View style={s.sectionHead}><View><Text style={s.sectionTitle}>Risk Command</Text><Text style={s.sectionSub}>Live protection envelope</Text></View><Ionicons name="shield-half-outline" size={21} color={colors.green}/></View>
    <Panel>
      <View style={s.riskTop}><View><Text style={s.label}>RISK HEALTH</Text><Text style={[s.riskState,{color:emergency?colors.red:colors.green}]}>{emergency?"LOCKED":"RISK GATES ON"}</Text></View><Text style={s.riskPct}>{Number.isFinite(dd)?Math.round(ddPct)+"% USED":"BROKER DD UNAVAILABLE"}</Text></View>
      <Gauge value={ddPct}/>
      <View style={s.riskGrid}><Metric label="RISK / TRADE" value={(data?.bot?.risk_per_trade??0.5)+"%"}/><Metric label="DAILY LOSS" value={(data?.bot?.daily_loss_limit??2)+"%"}/><Metric label="OPEN TRADES" value={(data?.bot?.open_trades??0)+"/"+(data?.bot?.max_open_trades??3)}/><Metric label="MAX DD" value={maxDd+"%"}/></View>
    </Panel>

    <View style={s.sectionHead}><View><Text style={s.sectionTitle}>Market Radar</Text><Text style={s.sectionSub}>Highest-priority cloud signals</Text></View><Text style={s.live}>● LIVE</Text></View>
    <Panel>
      {markets.length===0?<View style={s.empty}><ActivityIndicator color={colors.green}/><Text style={s.sub}>Waiting for market data…</Text></View>:markets.slice(0,6).map((m:any,i:number)=>{
        const buy=m.signal==="BUY",sell=m.signal==="SELL",c=buy?colors.green:sell?colors.red:colors.muted;
        return <View key={m.symbol} style={[s.marketRow,i>0&&s.rowBorder]}><View style={[s.marketIcon,{borderColor:c+"55"}]}><Ionicons name="pulse-outline" size={17} color={c}/></View><View style={{flex:1}}><Text style={s.symbol}>{m.symbol}</Text><Text style={s.marketSub}>{m.signal??"NO TRADE"} · cloud score</Text></View><View style={s.scoreBox}><Text style={[s.score,{color:c}]}>{m.score??0}</Text><Text style={[s.direction,{color:c}]}>{buy?"BUY":sell?"SELL":"WAIT"}</Text></View></View>
      })}<Pressable style={s.secondary} onPress={()=>router.push("/(tabs)/markets")}><Text style={s.secondaryText}>OPEN FULL MARKET TERMINAL</Text><Ionicons name="chevron-forward" size={15} color={colors.green}/></Pressable>
    </Panel>

    {notice?<Panel><View style={s.noticeHead}><Ionicons name="flash-outline" size={17} color={colors.green}/><Text style={s.noticeTitle}>LATEST EVENT</Text></View><Text style={s.noticeText}>{notice.payload?.symbol?`${notice.payload.symbol} · ${notice.payload.action??notice.payload.reason??""}`:notice.payload?.message??"Trading engine updated."}</Text></Panel>:null}

    {emergency?<Panel><View style={s.lock}><Ionicons name="lock-closed" size={18} color={colors.red}/><View style={{flex:1}}><Text style={s.lockTitle}>EMERGENCY STOP ACTIVE</Text><Text style={s.lockText}>New trading is blocked until protection is reset.</Text></View></View><Pressable style={s.reset} onPress={async()=>{await api.resetEmergency();load()}}><Text style={s.resetText}>RESET PROTECTION</Text></Pressable></Panel>:<Pressable style={s.emergency} onPress={async()=>{await api.emergencyStop();load()}}><Ionicons name="stop-circle-outline" size={19} color={colors.white}/><Text style={s.emergencyText}>EMERGENCY STOP</Text></Pressable>}
    <Text style={s.footer}>TradeGuard Trading Master · cTrader cloud · execution safety locked</Text>
  </ScrollView>
}
const s=StyleSheet.create({
 screen:{flex:1,backgroundColor:colors.background},c:{padding:18,paddingTop:58,paddingBottom:112,gap:14},
 header:{flexDirection:"row",justifyContent:"space-between",alignItems:"center"},eyebrow:{color:colors.green,fontSize:8,fontWeight:"900",letterSpacing:1.8},title:{color:colors.text,fontSize:29,fontWeight:"900",marginTop:3},sub:{color:colors.muted,fontSize:10,marginTop:4},logo:{width:50,height:50,borderRadius:17,backgroundColor:"#08261a",borderWidth:1,borderColor:colors.borderStrong,alignItems:"center",justifyContent:"center",...shadows.glow},
 statusRow:{flexDirection:"row",flexWrap:"wrap",gap:7},heartbeat:{fontSize:8,fontWeight:"900",letterSpacing:.7,marginTop:-7},pill:{flexDirection:"row",alignItems:"center",gap:6,paddingHorizontal:9,paddingVertical:7,borderRadius:radii.pill,borderWidth:1},pillDot:{width:6,height:6,borderRadius:6},pillText:{fontSize:8,fontWeight:"900",letterSpacing:.7},
 label:{color:colors.muted,fontSize:8,fontWeight:"900",letterSpacing:1.2},heroTop:{flexDirection:"row",alignItems:"center"},hero:{color:colors.text,fontSize:34,fontWeight:"900",marginTop:5},accountMeta:{color:colors.muted,fontSize:9,marginTop:5},liveRing:{width:50,height:50,borderRadius:25,backgroundColor:"#08261a",borderWidth:1,borderColor:colors.borderGlow,alignItems:"center",justifyContent:"center"},divider:{height:1,backgroundColor:colors.border,marginVertical:15},metrics:{flexDirection:"row",justifyContent:"space-between"},metric:{flex:1},metricLabel:{color:colors.muted2,fontSize:7,fontWeight:"900",letterSpacing:.8},metricValue:{color:colors.text,fontSize:13,fontWeight:"900",marginTop:5},
 sectionHead:{flexDirection:"row",justifyContent:"space-between",alignItems:"center",marginTop:2},sectionTitle:{color:colors.text,fontSize:16,fontWeight:"900"},sectionSub:{color:colors.muted,fontSize:10,marginTop:3},
 riskTop:{flexDirection:"row",justifyContent:"space-between",alignItems:"center"},riskState:{fontSize:20,fontWeight:"900",marginTop:4},riskPct:{color:colors.muted,fontSize:9,fontWeight:"900"},gauge:{height:7,borderRadius:8,backgroundColor:colors.surface3,overflow:"hidden",marginTop:14},gaugeFill:{height:7,backgroundColor:colors.green,borderRadius:8},riskGrid:{flexDirection:"row",flexWrap:"wrap",rowGap:15,marginTop:18},
 live:{color:colors.green,fontSize:8,fontWeight:"900",letterSpacing:1},marketRow:{flexDirection:"row",alignItems:"center",paddingVertical:12,gap:10},rowBorder:{borderTopWidth:1,borderTopColor:colors.border},marketIcon:{width:35,height:35,borderRadius:11,backgroundColor:"#08261a",borderWidth:1,alignItems:"center",justifyContent:"center"},symbol:{color:colors.text,fontSize:14,fontWeight:"900"},marketSub:{color:colors.muted,fontSize:9,marginTop:3},scoreBox:{alignItems:"flex-end"},score:{fontSize:17,fontWeight:"900"},direction:{fontSize:7,fontWeight:"900",marginTop:2},secondary:{height:42,borderRadius:11,borderWidth:1,borderColor:colors.border,backgroundColor:colors.surface2,flexDirection:"row",alignItems:"center",justifyContent:"center",gap:6,marginTop:7},secondaryText:{color:colors.green,fontSize:8,fontWeight:"900",letterSpacing:.6},
 noticeHead:{flexDirection:"row",alignItems:"center",gap:7},noticeTitle:{color:colors.green,fontSize:9,fontWeight:"900",letterSpacing:1},noticeText:{color:colors.text,fontSize:12,fontWeight:"800",marginTop:7},lock:{flexDirection:"row",alignItems:"center",gap:10},lockTitle:{color:colors.red,fontSize:11,fontWeight:"900"},lockText:{color:colors.muted,fontSize:10,marginTop:4},reset:{marginTop:13,borderWidth:1,borderColor:colors.green,borderRadius:10,padding:11,alignItems:"center"},resetText:{color:colors.green,fontSize:9,fontWeight:"900"},emergency:{height:50,borderRadius:14,backgroundColor:colors.redDeep,borderWidth:1,borderColor:"#c83a50",alignItems:"center",justifyContent:"center",flexDirection:"row",gap:8},emergencyText:{color:colors.white,fontSize:10,fontWeight:"900",letterSpacing:.7},inline:{flexDirection:"row",alignItems:"center",gap:8},error:{color:"#ffb5bf",fontSize:11,flex:1},empty:{alignItems:"center",gap:8,paddingVertical:16},footer:{color:colors.muted2,fontSize:8,textAlign:"center",marginTop:2}
});
