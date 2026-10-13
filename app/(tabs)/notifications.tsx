import {useCallback,useEffect,useState} from "react";
import {ActivityIndicator,Alert,Linking,Pressable,RefreshControl,ScrollView,StyleSheet,Text,View} from "react-native";
import {api} from "../../src/api";
import {Panel} from "../../src/components/Panel";
import {colors,radii,shadows} from "../../src/theme";

type Event={id:number;type:string;payload?:any;created_at:string};

function label(type:string){
  if(type==="notification_signal") return "NEW SIGNAL";
  if(type==="notification_trade_opened") return "TRADE OPENED";
  if(type==="notification_trade_closed") return "TRADE CLOSED";
  if(type==="notification_trade_partially_closed") return "PARTIAL CLOSE";
  if(type==="notification_trade_close_failed") return "CLOSE FAILED";
  if(type==="notification_trade_close_unconfirmed") return "CLOSE UNCONFIRMED";
  if(type==="notification_position_protected") return "PROTECTION CONFIRMED";
  if(type==="notification_protection_failed") return "PROTECTION FAILED";
  if(type==="notification_protection_unconfirmed") return "PROTECTION UNCONFIRMED";
  if(type==="notification_trade_execution_failed") return "EXECUTION FAILED";
  if(type==="notification_trade_execution_blocked") return "EXECUTION BLOCKED";
  if(type==="notification_trade_approval_needed") return "APPROVAL NEEDED";
  if(type==="notification_emergency_stop") return "EMERGENCY STOP";
  if(type==="notification_close_all_confirmed") return "CLOSE ALL CONFIRMED";
  if(type==="notification_close_all_unconfirmed") return "CLOSE ALL NEEDS REVIEW";
  if(type==="notification_test") return "PUSH TEST";
  return "TRADEGUARD ALERT";
}

function message(e:Event){
  const p=e.payload||{};
  if(e.type==="notification_signal") return `${p.symbol||"Market"} · ${p.action||"Signal"} · Score ${p.score??"—"} · Entry ${p.entry??"—"} · SL ${p.stop_loss??"—"} · TP ${p.take_profit??"—"}`;
  if(e.type==="notification_trade_opened") return `${p.symbol||"Market"} · ${p.side||""} · Entry ${p.entry??"—"}`;
  if(e.type==="notification_trade_closed" && p.position_id) return `Position #${p.position_id} · cTrader ${String(p.environment||"selected").toUpperCase()} · ${p.status||p.result?.status||"close confirmed"}`;
  if(e.type==="notification_trade_closed") { const reason=p.reason==="take_profit"?"Take profit":p.reason==="stop_loss"?"Stop loss":"Closed"; const pnl=p.pnl===null||p.pnl===undefined||p.pnl===""?null:Number(p.pnl); return `${p.symbol||"Market"} · ${reason} · P/L ${pnl!==null&&Number.isFinite(pnl)?pnl.toFixed(2):"—"}`; }
  if(["notification_trade_partially_closed","notification_trade_close_failed","notification_trade_close_unconfirmed"].includes(e.type)) return `Position #${p.position_id||"—"} · cTrader ${String(p.environment||"selected").toUpperCase()} · ${p.result?.error||p.result?.status||p.status||"Check broker position"}`;
  if(["notification_position_protected","notification_protection_failed","notification_protection_unconfirmed"].includes(e.type)) return `Position #${p.position_id||"—"} · cTrader ${String(p.environment||"selected").toUpperCase()} · ${p.result?.error||p.result?.status||p.status||"Check broker protection"}`;
  if(e.type==="notification_trade_execution_failed") return `${p.symbol||"Market"} · ${p.side||p.action||"Trade"} · ${p.error||p.message||"Execution failed; check broker account"}`;
  if(e.type==="notification_close_all_confirmed") { if(p.result?.status==="no_open_positions") return `cTrader ${String(p.environment||"selected").toUpperCase()} · no open positions were found; nothing needed closing`; return `cTrader ${String(p.environment||"selected").toUpperCase()} · ${p.result?.confirmed_closed_count??0}/${p.result?.attempted_count??0} positions confirmed closed · close-all confirmed`; }
  if(e.type==="notification_close_all_unconfirmed") {
    const result=p.result||{};
    if(result.status==="failed" && !Object.prototype.hasOwnProperty.call(result,"attempted_count")) return `cTrader ${String(p.environment||"selected").toUpperCase()} · close-all request failed before broker closure could be verified · check broker positions immediately`;
    return `cTrader ${String(p.environment||"selected").toUpperCase()} · ${result.confirmed_closed_count??0}/${result.attempted_count??0} positions confirmed closed · check broker positions immediately`;
  }
  if(e.type==="notification_trade_execution_blocked") return `${p.symbol||"Market"} · ${p.reason||"Execution blocked by safety checks"}`;
  if(e.type==="notification_trade_approval_needed") return `${p.symbol||"Market"} · ${p.action||"Trade"} · Approval required; no broker execution is implied · cTrader ${String(p.environment||"").toLowerCase()==="live"?"LIVE":String(p.environment||"").toLowerCase()==="demo"?"Demo":"account"}`;
  if(e.type==="notification_test") return p.ok ? "Expo accepted the test alert; check the phone notification tray. Device delivery is not confirmed here." : `Push test failed: ${p.message||p.error||"Expo rejected the notification"}`;
  return p.message||"Trading event";
}

export default function Notifications(){
  const [events,setEvents]=useState<Event[]>([]);
  const [refreshing,setRefreshing]=useState(false);
  const [testing,setTesting]=useState(false);
  const [pushRegistered,setPushRegistered]=useState<boolean|null>(null);
  const [loadError,setLoadError]=useState("");

  const load=useCallback(async()=>{
    try{
      const [eventsResult,statusResult]=await Promise.allSettled([
        api.notificationEvents(),
        api.notificationStatus(),
      ]);
      const failures:string[]=[];
      if(eventsResult.status==="fulfilled")setEvents((eventsResult.value as any)?.events||[]);
      else failures.push("Could not refresh alert history.");
      if(statusResult.status==="fulfilled")setPushRegistered(Boolean((statusResult.value as any)?.registered));
      else failures.push("Could not verify push registration.");
      setLoadError(failures.join(" "));
    }catch{
      setLoadError("Could not contact the alert service. Refresh and verify notification delivery.");
    }
  },[]);

  const refresh=useCallback(async()=>{
    setRefreshing(true);
    await load();
    setRefreshing(false);
  },[load]);

  const sendTest=useCallback(async()=>{
    setTesting(true);
    try{
      const result=await api.testNotification();
      Alert.alert("Push test status",result.message||"Expo accepted the test alert. Check the phone notification tray; device delivery is not confirmed.");
      await load();
    }catch(error:any){
      const raw=String(error?.message||error);
      let message=raw;
      try{
        const parsed=JSON.parse(raw);
        message=parsed?.detail||parsed?.message||raw;
      }catch{}
      Alert.alert("Push test failed",message);
      await load();
    }finally{
      setTesting(false);
    }
  },[load]);

  useEffect(()=>{
    load();
    const t=setInterval(load,30000);
    return()=>clearInterval(t);
  },[load]);

  return <ScrollView style={s.screen} contentContainerStyle={s.c} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={colors.green}/>}><View style={s.header}><View style={{flex:1}}><Text style={s.eyebrow}>TRADEGUARD / EVENT CENTER</Text><Text style={s.title}>Alert Center</Text><Text style={s.sub}>Execution events, risk warnings and market signals. Push acceptance is not proof of device delivery.</Text></View><View style={s.countChip}><Text style={s.countValue}>{events.length}</Text><Text style={s.countLabel}>EVENTS</Text></View></View>
    {loadError!==""&&<Panel><Text style={s.statusText}>{loadError}</Text></Panel>}
    <Panel><View style={s.centerHead}><View><Text style={s.label}>ALERT CHANNEL</Text><Text style={s.channelState}>{pushRegistered===true?"READY":pushRegistered===false?"NOT REGISTERED":"STATUS UNKNOWN"}</Text></View><View style={[s.readyPill,{borderColor:pushRegistered===true?colors.borderGlow:colors.border}]}><View style={[s.statusDot,{backgroundColor:pushRegistered===true?colors.green:pushRegistered===false?"#F59E0B":colors.muted}]}/><Text style={[s.readyText,{color:pushRegistered===true?colors.green:pushRegistered===false?colors.amber:colors.muted}]}>{pushRegistered===true?"TOKEN REGISTERED":pushRegistered===false?"NOT REGISTERED":"CHECKING STATUS"}</Text></View></View>
      <View style={s.divider}/><View style={s.statusRow}>
        <View style={[s.statusDot,{backgroundColor:pushRegistered?colors.green:"#F59E0B"}]}/>
        <View style={s.statusBody}>
          <Text style={s.statusTitle}>{pushRegistered===true?"PUSH TOKEN REGISTERED":pushRegistered===false?"PUSH ALERTS NOT REGISTERED":"PUSH STATUS UNCONFIRMED"}</Text>
          <Text style={s.statusText}>{pushRegistered===true?"A notification token is registered for this phone. Actual device delivery is not confirmed; use a test alert to check.":pushRegistered===false?"Open the latest app build and allow notifications to register this phone.":"TradeGuard could not verify this phone's registration. Refresh status and send a test alert."}</Text>
        </View>
      </View>
      {pushRegistered!==true && <Pressable onPress={()=>Linking.openSettings()} style={({pressed})=>[s.settingsButton,pressed&&s.testPressed]}>
        <Text style={s.settingsText}>OPEN NOTIFICATION SETTINGS</Text>
      </Pressable>}
      <Pressable onPress={sendTest} disabled={testing} style={({pressed})=>[s.testButton,pressed&&s.testPressed,testing&&s.disabled]}>
        {testing?<ActivityIndicator size="small" color={colors.background}/>:<Text style={s.testText}>SEND TEST ALERT</Text>}
      </Pressable>
    </Panel>
    <Text style={s.section}>LATEST EVENTS</Text>
    {events.length===0?<Panel><Text style={s.empty}>No notifications yet.</Text></Panel>:events.map(e=>{
      const urgent=["notification_emergency_stop","notification_trade_close_failed","notification_trade_close_unconfirmed","notification_protection_failed","notification_protection_unconfirmed","notification_close_all_unconfirmed","notification_trade_execution_failed","notification_trade_execution_blocked"].includes(e.type);
      const positive=["notification_position_protected","notification_close_all_confirmed"].includes(e.type);
      const closedPnl=e.type==="notification_trade_closed"&&e.payload?.pnl!==null&&e.payload?.pnl!==undefined&&e.payload?.pnl!==""?Number(e.payload.pnl):null;
      const closedPnlKnown=closedPnl!==null&&Number.isFinite(closedPnl);
      const eventColor=urgent||(e.type==="notification_trade_closed"&&closedPnlKnown&&closedPnl<0)?colors.red:e.type==="notification_trade_closed"?(closedPnlKnown&&closedPnl>0?colors.green:colors.amber):positive||e.type==="notification_signal"?colors.green:colors.amber;
      return <Panel key={e.id}><View style={s.row}><View style={[s.dot,{backgroundColor:eventColor}]}/><View style={s.body}><Text style={[s.type,{color:eventColor}]}>{label(e.type)}</Text><Text style={s.msg}>{message(e)}</Text><Text style={s.time}>{new Date(e.created_at).toLocaleString()}</Text></View></View></Panel>;
    })}</ScrollView>
}

const s=StyleSheet.create({
  screen:{flex:1,backgroundColor:colors.background},
  c:{padding:18,paddingTop:58,gap:12,paddingBottom:112},
  header:{flexDirection:"row",justifyContent:"space-between",alignItems:"flex-start",gap:10},
  eyebrow:{color:colors.green,fontSize:8,fontWeight:"900",letterSpacing:1.5},
  title:{color:colors.text,fontSize:28,fontWeight:"900",marginTop:3},
  countChip:{width:54,height:48,borderRadius:radii.md,backgroundColor:colors.surface2,borderWidth:1,borderColor:colors.border,alignItems:"center",justifyContent:"center",...shadows.card},
  countValue:{color:colors.text,fontSize:16,fontWeight:"900"},countLabel:{color:colors.muted,fontSize:6,fontWeight:"900",letterSpacing:.8,marginTop:2},
  sub:{color:colors.muted,fontSize:10,lineHeight:15,marginTop:4},
  label:{color:colors.muted,fontSize:8,fontWeight:"900",letterSpacing:1.1},section:{color:colors.green,fontSize:9,fontWeight:"900",letterSpacing:1.1,marginTop:3},
  centerHead:{flexDirection:"row",justifyContent:"space-between",alignItems:"center"},channelState:{color:colors.text,fontSize:16,fontWeight:"900",marginTop:4},
  readyPill:{flexDirection:"row",alignItems:"center",gap:5,paddingHorizontal:8,paddingVertical:6,borderRadius:radii.pill,borderWidth:1,backgroundColor:colors.surface2},readyText:{fontSize:7,fontWeight:"900",letterSpacing:.7},divider:{height:1,backgroundColor:colors.border,marginVertical:10},
  statusRow:{flexDirection:"row",gap:12,alignItems:"flex-start"},
  statusDot:{width:9,height:9,borderRadius:9,marginTop:4},
  statusBody:{flex:1},
  statusTitle:{color:colors.text,fontSize:12,fontWeight:"900",letterSpacing:.8},
  statusText:{color:colors.muted,fontSize:11,lineHeight:16,marginTop:4},
  testButton:{marginTop:14,minHeight:44,borderRadius:12,backgroundColor:colors.green,alignItems:"center",justifyContent:"center"},
  testPressed:{opacity:.8},
  disabled:{opacity:.6},
  testText:{color:colors.background,fontSize:11,fontWeight:"900",letterSpacing:1},
  settingsButton:{marginTop:10,minHeight:42,borderRadius:12,borderWidth:1,borderColor:colors.border,alignItems:"center",justifyContent:"center"},
  settingsText:{color:colors.text,fontSize:10,fontWeight:"900",letterSpacing:1},
  row:{flexDirection:"row",gap:12},
  dot:{width:8,height:8,borderRadius:8,backgroundColor:colors.green,marginTop:5},
  body:{flex:1},
  type:{color:colors.green,fontSize:10,fontWeight:"900",letterSpacing:1},
  msg:{color:colors.text,fontSize:14,fontWeight:"800",marginTop:5},
  time:{color:colors.muted,fontSize:10,marginTop:6},
  empty:{color:colors.muted,fontSize:13}
});
