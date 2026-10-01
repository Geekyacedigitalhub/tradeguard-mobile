import {ScrollView,StyleSheet,Text,View,Pressable,ActivityIndicator} from "react-native";
import {Ionicons} from "@expo/vector-icons";
import {useEffect,useState} from "react";
import {Panel} from "../../src/components/Panel";
import {colors} from "../../src/theme";
import {api} from "../../src/api";

const symbols=["EURUSD","GBPUSD","USDJPY","XAUUSD","XAGUSD","BTCUSD","ETHUSD","NAS100","US30"];
const intervals=["5m","15m","1h"] as const;

export default function Strategy(){
  const [symbol,setSymbol]=useState("EURUSD");
  const [interval,setInterval]=useState<"5m"|"15m"|"1h">("15m");
  const [report,setReport]=useState<any>(null);
  const [loading,setLoading]=useState(false);
  const [error,setError]=useState("");

  const run=async()=>{
    setLoading(true); setError("");
    try{ setReport(await api.strategyBacktest(symbol,interval)); }
    catch(e:any){ setReport(null); setError(e?.message??"Validation unavailable"); }
    finally{ setLoading(false); }
  };

  useEffect(()=>{run()},[symbol,interval]);

  return <ScrollView style={s.screen} contentContainerStyle={s.c}>
    <View style={s.header}>
      <View>
        <Text style={s.eyebrow}>TRADEGUARD INTELLIGENCE</Text>
        <Text style={s.title}>Strategy Lab</Text>
        <Text style={s.sub}>Validate the rules before trusting the signal engine.</Text>
      </View>
      <View style={s.icon}><Ionicons name="analytics-outline" size={23} color={colors.green}/></View>
    </View>

    <Panel>
      <Text style={s.label}>MARKET</Text>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chips}>
        {symbols.map(x=><Pressable key={x} onPress={()=>setSymbol(x)} style={[s.chip,x===symbol&&s.chipActive]}><Text style={[s.chipText,x===symbol&&s.chipTextActive]}>{x}</Text></Pressable>)}
      </ScrollView>
      <Text style={[s.label,{marginTop:16}]}>TIMEFRAME</Text>
      <View style={s.intervalRow}>
        {intervals.map(x=><Pressable key={x} onPress={()=>setInterval(x)} style={[s.interval,x===interval&&s.intervalActive]}><Text style={[s.intervalText,x===interval&&s.intervalTextActive]}>{x.toUpperCase()}</Text></Pressable>)}
      </View>
    </Panel>

    {error?<Panel><View style={s.error}><Ionicons name="warning-outline" size={18} color={colors.red}/><Text style={s.errorText}>{error}</Text></View></Panel>:null}

    {loading?<Panel><View style={s.loading}><ActivityIndicator color={colors.green}/><Text style={s.sub}>Replaying historical candles without executing trades…</Text></View></Panel>
    :report?<><Panel>
      <View style={s.reportHead}>
        <View><Text style={s.label}>VALIDATION STATUS</Text><Text style={s.status}>{report.status==="ok"?"COMPLETED":report.status?.replace("_"," ").toUpperCase()}</Text></View>
        <View style={s.safe}><Ionicons name="shield-checkmark-outline" size={18} color={colors.green}/><Text style={s.safeText}>NO EXECUTION</Text></View>
      </View>
      {report.message?<Text style={s.sub}>{report.message}</Text>:null}
      <View style={s.grid}>
        <Metric label="TRADES" value={report.trades??0}/>
        <Metric label="WIN RATE" value={report.win_rate!=null?report.win_rate+"%":"—"}/>
        <Metric label="EXPECTANCY" value={report.expectancy_r!=null?report.expectancy_r+" R":"—"}/>
        <Metric label="TOTAL R" value={report.total_r!=null?report.total_r+" R":"—"}/>
        <Metric label="PROFIT FACTOR" value={report.profit_factor??"—"}/>
        <Metric label="MAX DD" value={report.max_drawdown_r!=null?report.max_drawdown_r+" R":"—"}/>
      </View>
    </Panel>
    {report.trades_sample?.length?<Panel>
      <Text style={s.section}>RECENT VALIDATED SETUPS</Text>
      {report.trades_sample.slice(-8).reverse().map((t:any,i:number)=><View key={i} style={s.tradeRow}>
        <View style={{flex:1}}><Text style={s.tradeSide}>{t.signal} · {t.outcome}</Text><Text style={s.sub}>Entry {t.entry} · Exit {t.exit}</Text></View>
        <Text style={[s.rValue,{color:Number(t.r)>=0?colors.green:colors.red}]}>{Number(t.r)>0?"+":""}{t.r}R</Text>
      </View>)}
    </Panel>:null}</>:null}

    <Panel><View style={s.note}><Ionicons name="information-circle-outline" size={18} color={colors.green}/><Text style={s.noteText}>Validation is evidence, not a promise. TradeGuard will use these results to improve filtering, risk rules, and strategy selection.</Text></View></Panel>
    <Pressable style={s.refresh} onPress={run}><Ionicons name="refresh-outline" size={18} color={colors.white}/><Text style={s.refreshText}>RUN VALIDATION AGAIN</Text></Pressable>
  </ScrollView>
}

function Metric({label,value}:{label:string;value:any}){
  return <View style={s.metric}><Text style={s.metricLabel}>{label}</Text><Text style={s.metricValue}>{String(value)}</Text></View>
}

const s=StyleSheet.create({
  screen:{flex:1,backgroundColor:colors.background},c:{padding:18,paddingTop:58,paddingBottom:32,gap:14},
  header:{flexDirection:"row",justifyContent:"space-between",alignItems:"center"},eyebrow:{color:colors.green,fontSize:9,fontWeight:"900",letterSpacing:1.2},title:{color:colors.text,fontSize:26,fontWeight:"900",marginTop:3},sub:{color:colors.muted,fontSize:11,lineHeight:16,marginTop:4},icon:{width:46,height:46,borderRadius:14,backgroundColor:"#09271b",borderWidth:1,borderColor:"#1b513a",alignItems:"center",justifyContent:"center"},
  label:{color:colors.muted,fontSize:8,fontWeight:"900",letterSpacing:1.1},chips:{gap:8,paddingTop:10},chip:{paddingHorizontal:12,paddingVertical:9,borderRadius:10,borderWidth:1,borderColor:colors.border,backgroundColor:colors.surface2},chipActive:{borderColor:"#1b6a48",backgroundColor:"#09271b"},chipText:{color:colors.muted,fontSize:10,fontWeight:"900"},chipTextActive:{color:colors.green},
  intervalRow:{flexDirection:"row",gap:8,marginTop:10},interval:{flex:1,paddingVertical:10,borderRadius:10,borderWidth:1,borderColor:colors.border,alignItems:"center"},intervalActive:{backgroundColor:"#09271b",borderColor:"#1b6a48"},intervalText:{color:colors.muted,fontSize:10,fontWeight:"900"},intervalTextActive:{color:colors.green},
  loading:{alignItems:"center",gap:9,paddingVertical:8},error:{flexDirection:"row",gap:8,alignItems:"center"},errorText:{color:"#ffb5bf",fontSize:11,flex:1},
  reportHead:{flexDirection:"row",justifyContent:"space-between",alignItems:"center"},status:{color:colors.text,fontSize:17,fontWeight:"900",marginTop:3},safe:{flexDirection:"row",alignItems:"center",gap:5},safeText:{color:colors.green,fontSize:8,fontWeight:"900"},
  grid:{flexDirection:"row",flexWrap:"wrap",marginTop:16,borderTopWidth:1,borderTopColor:colors.border},metric:{width:"50%",paddingTop:13,paddingBottom:4},metricLabel:{color:colors.muted,fontSize:8,fontWeight:"800",letterSpacing:.8},metricValue:{color:colors.text,fontSize:17,fontWeight:"900",marginTop:4},
  section:{color:colors.green,fontSize:9,fontWeight:"900",letterSpacing:1.1,marginBottom:7},tradeRow:{flexDirection:"row",alignItems:"center",paddingVertical:10,borderTopWidth:1,borderTopColor:colors.border},tradeSide:{color:colors.text,fontSize:11,fontWeight:"900"},rValue:{fontSize:15,fontWeight:"900"},note:{flexDirection:"row",gap:8},noteText:{color:colors.muted,fontSize:10,lineHeight:15,flex:1},refresh:{height:48,borderRadius:13,backgroundColor:"#123e2b",alignItems:"center",justifyContent:"center",flexDirection:"row",gap:8},refreshText:{color:colors.white,fontSize:10,fontWeight:"900",letterSpacing:.7}
});
