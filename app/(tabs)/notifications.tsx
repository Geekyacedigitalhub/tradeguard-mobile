import {useCallback,useEffect,useState} from "react";
import {ActivityIndicator,Alert,Linking,Pressable,RefreshControl,ScrollView,StyleSheet,Text,View} from "react-native";
import {api} from "../../src/api";
import {Panel} from "../../src/components/Panel";
import {colors} from "../../src/theme";

type Event={id:number;type:string;payload?:any;created_at:string};

function label(type:string){
  if(type==="notification_signal") return "NEW SIGNAL";
  if(type==="notification_trade_opened") return "TRADE OPENED";
  if(type==="notification_trade_closed") return "TRADE CLOSED";
  if(type==="notification_trade_approval_needed") return "AI APPROVED";
  if(type==="notification_emergency_stop") return "EMERGENCY STOP";
  if(type==="notification_test") return "PUSH TEST";
  return "TRADEGUARD ALERT";
}

function message(e:Event){
  const p=e.payload||{};
  if(e.type==="notification_signal") return `${p.symbol||"Market"} · ${p.action||"Signal"} · Score ${p.score??"—"} · Entry ${p.entry??"—"} · SL ${p.stop_loss??"—"} · TP ${p.take_profit??"—"}`;
  if(e.type==="notification_trade_opened") return `${p.symbol||"Market"} · ${p.side||""} · Entry ${p.entry??"—"}`;
  if(e.type==="notification_trade_closed") return `${p.symbol||"Market"} · ${p.reason==="take_profit"?"Take profit":"Stop loss"} · P/L ${Number(p.pnl||0).toFixed(2)}`;
  if(e.type==="notification_trade_approval_needed") return `${p.symbol||"Market"} · ${p.action||""} · AI approved while you were away · MT5 demo`;
  if(e.type==="notification_test") return p.ok ? "Push notifications are connected and working." : `Push test failed: ${p.message||p.error||"Expo rejected the notification"}`;
  return p.message||"Trading event";
}

export default function Notifications(){
  const [events,setEvents]=useState<Event[]>([]);
  const [refreshing,setRefreshing]=useState(false);
  const [testing,setTesting]=useState(false);
  const [pushRegistered,setPushRegistered]=useState<boolean|null>(null);

  const load=useCallback(async()=>{
    try{
      const [eventsResult,statusResult]=await Promise.all([
        api.notificationEvents(),
        api.notificationStatus(),
      ]);
      setEvents((eventsResult as any)?.events||[]);
      setPushRegistered(Boolean((statusResult as any)?.registered));
    }catch{}
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
      Alert.alert("TradeGuard",result.message||"Test notification sent.");
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
    const t=setInterval(load,5000);
    return()=>clearInterval(t);
  },[load]);

  return <ScrollView style={s.screen} contentContainerStyle={s.c} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={colors.green}/>}><Text style={s.title}>Notifications</Text><Text style={s.sub}>Trading activity and alerts</Text>
    <Panel>
      <View style={s.statusRow}>
        <View style={[s.statusDot,{backgroundColor:pushRegistered?colors.green:"#F59E0B"}]}/>
        <View style={s.statusBody}>
          <Text style={s.statusTitle}>{pushRegistered?"PUSH ALERTS READY":"PUSH ALERTS NOT REGISTERED"}</Text>
          <Text style={s.statusText}>{pushRegistered?"This phone is registered for TradeGuard alerts.":"Open the latest app build and allow notifications to connect this phone."}</Text>
        </View>
      </View>
      {!pushRegistered && <Pressable onPress={()=>Linking.openSettings()} style={({pressed})=>[s.settingsButton,pressed&&s.testPressed]}>
        <Text style={s.settingsText}>OPEN NOTIFICATION SETTINGS</Text>
      </Pressable>}
      <Pressable onPress={sendTest} disabled={testing} style={({pressed})=>[s.testButton,pressed&&s.testPressed,testing&&s.disabled]}>
        {testing?<ActivityIndicator size="small" color={colors.background}/>:<Text style={s.testText}>SEND TEST ALERT</Text>}
      </Pressable>
    </Panel>
    {events.length===0?<Panel><Text style={s.empty}>No notifications yet.</Text></Panel>:events.map(e=><Panel key={e.id}><View style={s.row}><View style={s.dot}/><View style={s.body}><Text style={s.type}>{label(e.type)}</Text><Text style={s.msg}>{message(e)}</Text><Text style={s.time}>{new Date(e.created_at).toLocaleString()}</Text></View></View></Panel>)}</ScrollView>
}

const s=StyleSheet.create({
  screen:{flex:1,backgroundColor:colors.background},
  c:{padding:18,paddingTop:58,gap:12,paddingBottom:30},
  title:{color:colors.text,fontSize:28,fontWeight:"900"},
  sub:{color:colors.muted,fontSize:12,marginBottom:4},
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
