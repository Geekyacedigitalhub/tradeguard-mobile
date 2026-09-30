import {ScrollView,StyleSheet,Text,View,Pressable,ActivityIndicator,Image} from "react-native";
import {Ionicons} from "@expo/vector-icons";
import {useEffect,useState} from "react";
import {Panel} from "../../src/components/Panel";
import {colors} from "../../src/theme";
import {api} from "../../src/api";
import logo from "../../assets/tradeguard-icon.png";

export default function Home(){
  const [data,setData]=useState<any>(null);
  const [broker,setBroker]=useState<any>(null);
  const [err,setErr]=useState("");
  const [notice,setNotice]=useState<any>(null);
  const brokerStale=!!broker?.connected&&broker?.last_seen ? Date.now()-new Date(broker.last_seen).getTime()>45000 : false;
  const load=()=>api.account().then(setData).catch(e=>setErr(e.message));
  const loadBroker=()=>api.broker().then(setBroker).catch(()=>setBroker(null));
  const loadNotifications=()=>api.notificationEvents().then((r:any)=>{const event=r?.events?.[0];if(event)setNotice(event)}).catch(()=>{});
  useEffect(()=>{load();loadBroker();loadNotifications();const timer=setInterval(load,5000);const bt=setInterval(loadBroker,5000);const nt=setInterval(loadNotifications,5000);return()=>{clearInterval(timer);clearInterval(bt);clearInterval(nt)}},[]);
  const markets:any[]=data?.markets??[];
  const running=!!data?.bot?.running;
  const emergency=!!data?.bot?.emergency_stopped;

  return <ScrollView style={s.screen} contentContainerStyle={s.c}>
    <View style={s.header}>
      <View style={s.brand}>
        <Image source={logo} style={s.logo}/>
        <View><Text style={s.brandName}>TRADEGUARD</Text><Text style={s.brandSub}>TRADING CONTROL CENTER</Text></View>
      </View>
      <View style={[s.statusPill,running?s.livePill:s.offPill]}>
        <View style={[s.statusDot,{backgroundColor:running?colors.green:colors.muted}]}/>
        <Text style={[s.statusText,{color:running?colors.green:colors.muted}]}>{running?"LIVE":"IDLE"}</Text>
      </View>
    </View>

    {err?<View style={s.error}><Ionicons name="cloud-offline-outline" size={16} color={colors.red}/><Text style={s.errorText}>Backend unavailable: {err}</Text></View>:null}

    <Panel>
      <View style={s.brokerHead}>
        <View><Text style={s.eyebrow}>BROKER CONNECTION</Text><Text style={s.brokerName}>{broker?.provider??"MT5 Broker"}</Text><Text style={s.sub}>{broker?.environment??"paper"} environment</Text></View>
        <View style={[s.connectionBadge,broker?.connected?s.connected:s.disconnected]}>
          <View style={[s.statusDot,{backgroundColor:broker?.connected?colors.green:colors.red}]}/>
          <Text style={[s.connectionText,{color:broker?.connected?colors.green:colors.red}]}>{broker?.connected?"CONNECTED":"OFFLINE"}</Text>
        </View>
      </View>
      {broker?.account?<Text style={s.account}>Account {broker.account}</Text>:null}
      {brokerStale?<Text style={s.warning}>MT5 bridge has stopped reporting. Broker data is hidden until it reconnects.</Text>:null}
    </Panel>

    <View style={s.balanceCard}>
      <View style={s.balanceTop}>
        <View><Text style={s.balanceLabel}>TOTAL BALANCE</Text><Text style={s.balance}>{data?.balance??"—"}</Text></View>
        <View style={s.balanceIcon}><Ionicons name="wallet-outline" size={24} color={colors.green}/></View>
      </View>
      <View style={s.divider}/>
      <View style={s.balanceGrid}>
        <View><Text style={s.metricLabel}>EQUITY</Text><Text style={s.metricValue}>{data?.equity??"—"}</Text></View>
        <View><Text style={s.metricLabel}>TODAY P/L</Text><Text style={[s.metricValue,s.positive]}>{data?.today_pl??"—"}</Text></View>
        <View><Text style={s.metricLabel}>DRAWDOWN</Text><Text style={s.metricValue}>{data?.drawdown??"—"}</Text></View>
      </View>
    </View>

    {notice?<Panel><View style={s.noticeHead}><Ionicons name="notifications-outline" size={18} color={colors.green}/><Text style={s.noticeTitle}>{notice.type==="notification_trade_closed"?"TRADE CLOSED":notice.type==="notification_trade_opened"?"TRADE OPENED":notice.type==="notification_emergency_stop"?"EMERGENCY STOP":"NEW SIGNAL"}</Text></View><Text style={s.noticeText}>{notice.payload?.symbol ? notice.payload.symbol+" · "+(notice.payload.action??notice.payload.reason??"") : notice.payload?.message}</Text></Panel>:null}

    <View style={s.sectionHead}><View><Text style={s.sectionTitle}>Risk & Protection</Text><Text style={s.sectionSub}>Live account safeguards</Text></View><Ionicons name="shield-checkmark-outline" size={22} color={colors.green}/></View>
    <Panel>
      <View style={s.riskHead}><Text style={s.riskMain}>Risk status</Text><Text style={s.safe}>{data?.bot?.open_trades??0}/{data?.bot?.max_open_trades??0} OPEN</Text></View>
      <View style={s.riskRow}><Text style={s.sub}>Daily loss limit</Text><Text style={s.value}>{data?.bot?.daily_loss_limit??0}%</Text></View>
      <View style={s.riskRow}><Text style={s.sub}>Current drawdown</Text><Text style={s.value}>{data?.drawdown??0}% / {data?.bot?.max_drawdown??0}%</Text></View>
      <View style={s.riskRow}><Text style={s.sub}>Risk per trade</Text><Text style={s.value}>{data?.bot?.risk_per_trade??0}%</Text></View>
    </Panel>

    {emergency?<Panel><View style={s.lockHead}><Ionicons name="warning-outline" size={21} color={colors.red}/><Text style={s.lockTitle}>EMERGENCY STOP ACTIVE</Text></View><Text style={s.lockText}>New trading is locked until you reset the emergency stop.</Text><Pressable style={s.reset} onPress={async()=>{await api.resetEmergency();load()}}><Text style={s.resetText}>RESET EMERGENCY STOP</Text></Pressable></Panel>
    :<Pressable style={s.emergency} onPress={async()=>{await api.emergencyStop();load()}}><Ionicons name="stop-circle-outline" size={20} color={colors.white}/><Text style={s.emergencyText}>EMERGENCY STOP</Text></Pressable>}

    <View style={s.sectionHead}><View><Text style={s.sectionTitle}>Market Scanner</Text><Text style={s.sectionSub}>Current engine signals</Text></View><Text style={s.live}>LIVE · 5S</Text></View>
    <Panel>
      {markets.length===0?<View style={s.empty}><ActivityIndicator color={colors.green}/><Text style={s.sub}>Waiting for market data…</Text></View>
      :markets.map((m,i)=><View key={m.symbol} style={[s.marketRow,i?s.rowBorder:null]}><View style={s.marketIcon}><Ionicons name="stats-chart-outline" size={17} color={colors.green}/></View><View style={{flex:1}}><Text style={s.symbol}>{m.symbol}</Text><Text style={s.sub}>{m.signal}</Text></View><Text style={[s.score,m.signal==="BUY"?s.buy:null]}>{m.score}</Text><Ionicons name={m.signal==="BUY"?"arrow-up-circle":"remove-circle-outline"} size={22} color={m.signal==="BUY"?colors.green:colors.muted}/></View>)}
    </Panel>
    <Text style={s.footer}>TradeGuard · live account data refreshes every 5 seconds</Text>
  </ScrollView>
}

const s=StyleSheet.create({
  screen:{flex:1,backgroundColor:colors.background},c:{padding:18,paddingTop:58,paddingBottom:30,gap:14},
  header:{flexDirection:"row",justifyContent:"space-between",alignItems:"center"},brand:{flexDirection:"row",alignItems:"center",gap:10},logo:{width:42,height:42,borderRadius:12},
  brandName:{color:colors.text,fontSize:15,fontWeight:"900",letterSpacing:1.5},brandSub:{color:colors.muted,fontSize:7,fontWeight:"800",letterSpacing:1.2,marginTop:2},
  statusPill:{flexDirection:"row",alignItems:"center",gap:6,paddingHorizontal:10,paddingVertical:7,borderRadius:20,borderWidth:1},livePill:{backgroundColor:"#09271b",borderColor:"#1b513a"},offPill:{backgroundColor:colors.surface,borderColor:colors.border},statusDot:{width:7,height:7,borderRadius:7},statusText:{fontSize:9,fontWeight:"900",letterSpacing:1},
  error:{flexDirection:"row",alignItems:"center",gap:7,padding:11,borderRadius:10,backgroundColor:"#241016",borderWidth:1,borderColor:"#4c202a"},errorText:{color:"#ffb5bf",fontSize:11,flex:1},
  brokerHead:{flexDirection:"row",justifyContent:"space-between",alignItems:"center"},eyebrow:{color:colors.green,fontSize:9,fontWeight:"900",letterSpacing:1.2},brokerName:{color:colors.text,fontSize:17,fontWeight:"900",marginTop:4},sub:{color:colors.muted,fontSize:11,marginTop:4},
  connectionBadge:{flexDirection:"row",alignItems:"center",gap:6,paddingHorizontal:9,paddingVertical:6,borderRadius:9,borderWidth:1},connected:{backgroundColor:"#08261a",borderColor:"#1a543b"},disconnected:{backgroundColor:"#281017",borderColor:"#55202b"},connectionText:{fontSize:8,fontWeight:"900",letterSpacing:1},
  account:{color:colors.muted,fontSize:10,marginTop:10},warning:{color:"#ffb5bf",fontSize:11,marginTop:9},
  balanceCard:{backgroundColor:colors.surface2,borderWidth:1,borderColor:colors.borderStrong,borderRadius:18,padding:18},balanceTop:{flexDirection:"row",justifyContent:"space-between",alignItems:"center"},balanceLabel:{color:colors.muted,fontSize:9,fontWeight:"900",letterSpacing:1.4},balance:{color:colors.text,fontSize:30,fontWeight:"900",marginTop:5},balanceIcon:{width:46,height:46,borderRadius:14,backgroundColor:"#09271b",alignItems:"center",justifyContent:"center",borderWidth:1,borderColor:"#1b513a"},divider:{height:1,backgroundColor:colors.border,marginVertical:16},
  balanceGrid:{flexDirection:"row",justifyContent:"space-between"},metricLabel:{color:colors.muted,fontSize:8,fontWeight:"800",letterSpacing:.8},metricValue:{color:colors.text,fontSize:12,fontWeight:"800",marginTop:5},positive:{color:colors.green},
  noticeHead:{flexDirection:"row",alignItems:"center",gap:8},noticeTitle:{color:colors.green,fontWeight:"900",fontSize:10,letterSpacing:1},noticeText:{color:colors.text,fontWeight:"700",fontSize:13,marginTop:7},
  sectionHead:{flexDirection:"row",justifyContent:"space-between",alignItems:"center",marginTop:2},sectionTitle:{color:colors.text,fontSize:16,fontWeight:"900"},sectionSub:{color:colors.muted,fontSize:10,marginTop:3},
  riskHead:{flexDirection:"row",justifyContent:"space-between",alignItems:"center"},riskMain:{color:colors.text,fontSize:14,fontWeight:"800"},safe:{color:colors.green,fontSize:9,fontWeight:"900"},riskRow:{flexDirection:"row",justifyContent:"space-between",paddingTop:11},value:{color:colors.text,fontSize:12,fontWeight:"800"},
  lockHead:{flexDirection:"row",alignItems:"center",gap:8},lockTitle:{color:colors.red,fontWeight:"900",fontSize:12},lockText:{color:colors.muted,fontSize:11,marginTop:8},reset:{marginTop:12,borderWidth:1,borderColor:colors.green,borderRadius:10,padding:11,alignItems:"center"},resetText:{color:colors.green,fontWeight:"900",fontSize:10},
  emergency:{height:52,borderRadius:14,backgroundColor:"#7f2635",alignItems:"center",justifyContent:"center",flexDirection:"row",gap:8},emergencyText:{color:colors.white,fontWeight:"900",fontSize:10,letterSpacing:.7},live:{color:colors.green,fontSize:9,fontWeight:"900",letterSpacing:1},
  marketRow:{flexDirection:"row",alignItems:"center",paddingVertical:12,gap:10},rowBorder:{borderTopWidth:1,borderTopColor:colors.border},marketIcon:{width:34,height:34,borderRadius:10,backgroundColor:"#09271b",alignItems:"center",justifyContent:"center"},symbol:{color:colors.text,fontWeight:"900",fontSize:14},score:{color:colors.text,fontSize:18,fontWeight:"900",width:38,textAlign:"right"},buy:{color:colors.green},empty:{alignItems:"center",gap:8,paddingVertical:14},footer:{color:"#53685e",fontSize:9,textAlign:"center",marginTop:2}
});