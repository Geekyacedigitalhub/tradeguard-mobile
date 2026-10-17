import {ScrollView,StyleSheet,Text,View,Pressable,ActivityIndicator,TextInput} from "react-native";
import {Ionicons} from "@expo/vector-icons";
import {useEffect,useRef,useState} from "react";
import {Panel} from "../../src/components/Panel";
import {colors,radii,shadows} from "../../src/theme";
import {api} from "../../src/api";

const symbols=["EURUSD","GBPUSD","USDJPY","XAUUSD","XAGUSD","BTCUSD","ETHUSD","NAS100","US30"];

function metricValue(value:any,digits=2,suffix=""){
  if(value===null||value===undefined||value==="")return "—";
  const n=Number(value);
  return Number.isFinite(n)?n.toFixed(digits)+suffix:"—";
}

function Metric({label,value}:{label:string;value:any}){
  return <View style={s.metric}><Text style={s.metricLabel}>{label}</Text><Text style={s.metricValue}>{String(value)}</Text></View>
}

export default function Strategy(){
  const [symbol,setSymbol]=useState("EURUSD");
  const [report,setReport]=useState<any>(null);
  const [live,setLive]=useState<any>(null);
  const [journalStats,setJournalStats]=useState<any>(null);
  const [costR,setCostR]=useState("0");
  const [loading,setLoading]=useState(false);
  const [error,setError]=useState("");
  const requestId=useRef(0);

  const loadLive=async()=>{
    const request=++requestId.current;
    setLoading(true);setError("");
    try{
      const [l,j]=await Promise.allSettled([
        api.strategyLive(symbol),
        api.journalStats()
      ]);
      const errors:string[]=[];
      if(request!==requestId.current)return;
      if(l.status==="fulfilled") setLive(l.value);
      else errors.push(l.reason?.message??"Live strategy data unavailable");
      if(j.status==="fulfilled") setJournalStats(j.value);
      if(errors.length) setError(errors.join("\n"));
    }catch(e:any){
      if(request===requestId.current)setError(e?.message??"Strategy intelligence unavailable");
    }finally{if(request===requestId.current)setLoading(false)}
  };

  const run=async()=>{
    const request=++requestId.current;
    setLoading(true);setError("");
    try{
      const cost=Math.max(0,Math.min(Number(costR)||0,0.5));
      const [v,l,j]=await Promise.allSettled([
        api.strategyValidate(symbol,cost),
        api.strategyLive(symbol),
        api.journalStats()
      ]);
      const errors:string[]=[];
      if(request!==requestId.current)return;
      if(v.status==="fulfilled") setReport(v.value);
      else errors.push(v.reason?.message??"Historical validation unavailable");
      if(l.status==="fulfilled") setLive(l.value);
      else errors.push(l.reason?.message??"Live strategy data unavailable");
      if(j.status==="fulfilled") setJournalStats(j.value);
      if(errors.length) setError(errors.join("\n"));
    }catch(e:any){
      if(request===requestId.current)setError(e?.message??"Strategy intelligence unavailable");
    }finally{if(request===requestId.current)setLoading(false)}
  };

  useEffect(()=>{loadLive()},[symbol]);

  const signal=live?.signal||{};
  const intel=live?.intelligence||{};
  const assessment=report?.assessment||{};
  const why=intel?.why_not_trade||[];
  const deep=live?.deep_analysis||{};
  const entry=Number(signal.entry), stop=Number(signal.stop_loss), target=Number(signal.take_profit);
  const validRisk=entry>0&&stop>0&&target>0&&((signal.signal==="BUY"&&stop<entry&&target>entry)||(signal.signal==="SELL"&&stop>entry&&target<entry));
  const riskReward=validRisk&&Math.abs(entry-stop)>0?`1 : ${(Math.abs(target-entry)/Math.abs(entry-stop)).toFixed(2)}`:"—";

  return <ScrollView style={s.screen} contentContainerStyle={s.c}>
    <View style={s.header}>
      <View><Text style={s.eyebrow}>TRADEGUARD INTELLIGENCE</Text><Text style={s.title}>Strategy Lab</Text><Text style={s.sub}>Live reasoning + historical walk-forward validation.</Text></View>
      <View style={s.icon}><Ionicons name="analytics-outline" size={23} color={colors.green}/></View>
    </View>
    <View style={s.terminalBar}>
      <View style={s.terminalStatus}><View style={s.terminalDot}/><Text style={s.terminalText}>CTRADER CLOUD</Text></View>
      <View style={s.terminalDivider}/>
      <Text style={s.terminalLock}>RESEARCH ONLY · NO ORDER EXECUTION</Text>
    </View>

    <Panel>
      <Text style={s.label}>MARKET</Text>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chips}>
        {symbols.map(x=><Pressable key={x} disabled={loading} onPress={()=>setSymbol(x)} style={[s.chip,x===symbol&&s.chipActive,loading&&{opacity:0.5}]}><Text style={[s.chipText,x===symbol&&s.chipTextActive]}>{x}</Text></Pressable>)}
      </ScrollView>
      <View style={s.costRow}><View style={{flex:1}}><Text style={s.label}>ESTIMATED COST / TRADE (R)</Text><Text style={s.sub}>Model spread + commission + slippage as a conservative R cost.</Text></View><TextInput value={costR} onChangeText={setCostR} editable={!loading} keyboardType="decimal-pad" style={[s.input,loading&&{opacity:0.5}]}/></View>
    </Panel>

    {error?<Panel><View style={s.error}><Ionicons name="warning-outline" size={18} color={colors.red}/><Text style={s.errorText}>{error}</Text></View></Panel>:null}
    {loading?<Panel><View style={s.loading}><ActivityIndicator color={colors.green}/><Text style={s.sub}>Scanning 1H → 15M → 5M and replaying historical candles…</Text></View></Panel>:null}

    {!loading&&live?<Panel>
      <View style={s.decisionHero}>
        <View style={{flex:1}}><Text style={s.label}>CURRENT DECISION</Text><Text style={[s.heroDecision,{color:deep.decision==="TRADE CANDIDATE"?colors.green:deep.decision==="WAIT"?colors.amber:colors.red}]}>{deep.decision??signal.signal??"NO TRADE"}</Text><Text style={s.heroReason}>{signal.reason??"No current setup."}</Text></View>
        <View style={s.scoreRing}><Text style={s.scoreNumber}>{metricValue(signal.score,0)}</Text><Text style={s.scoreCaption}>/ 100</Text></View>
      </View>
      <View style={s.confidenceBar}><View style={[s.confidenceFill,{width:`${Math.max(2,Math.min(100,Number(signal.score)||0))}%`,backgroundColor:deep.decision==="TRADE CANDIDATE"?colors.green:deep.decision==="WAIT"?colors.amber:colors.red}]}/></View>
      <View style={s.reportHead}>
        <View><Text style={s.label}>LIVE SETUP</Text><Text style={s.status}>{signal.signal??"NO TRADE"}</Text></View>
        <View style={s.livePill}><View style={s.dot}/><Text style={s.safeText}>MTF ENGINE</Text></View>
      </View>
      <View style={s.grid}>
        <Metric label="SCORE" value={metricValue(signal.score,0)}/>
        <Metric label="REGIME" value={intel.regime??"—"}/>
        <Metric label="SESSION" value={intel.session??"—"}/>
        <Metric label="1H" value={signal.timeframes?.["1h"]??"—"}/>
        <Metric label="15M" value={signal.timeframes?.["15m"]??"—"}/>
        <Metric label="5M TRIGGER" value={signal.entry_trigger??"waiting"}/>
        <Metric label="ENTRY" value={signal.entry??"—"}/>
        <Metric label="STOP" value={signal.stop_loss??"—"}/>
        <Metric label="TARGET" value={signal.take_profit??"—"}/>
        <Metric label="R:R" value={riskReward}/>
      </View>
    </Panel>:null}

    {!loading&&live?<Panel><Text style={s.section}>DEEP RESEARCH DECISION</Text><Text style={[s.deepDecision,{color:deep.decision==="TRADE CANDIDATE"?colors.green:deep.decision==="WAIT"?"#f2c94c":colors.red}]}>{deep.decision??"NO TRADE"} · {metricValue(deep.confluence,0)}/100</Text>{(deep.reasons||[]).slice(0,6).map((x:string,i:number)=><View key={i} style={s.reasonRow}><Ionicons name={deep.decision==="TRADE CANDIDATE"?"checkmark-circle-outline":"close-circle-outline"} size={16} color={deep.decision==="TRADE CANDIDATE"?colors.green:colors.red}/><Text style={s.reasonText}>{x}</Text></View>)}<Text style={s.sub}>Technical research gate only. News and fundamental risk must be checked before execution.</Text></Panel>:null}

    {!loading?<Panel>
      <Text style={s.section}>WHY TRADEGUARD IS / ISN'T TRADING</Text>
      {(why.length?why:(live?[deep.decision==="TRADE CANDIDATE"?"Deep research conditions support a trade candidate.":deep.decision==="WAIT"?"Deep research says WAIT; execution should remain blocked.":"Deep research says NO TRADE; execution should remain blocked."]:["Live strategy data is unavailable; no trading decision is being made."])).map((x:string,i:number)=><View key={i} style={s.reasonRow}><Ionicons name={deep.decision==="TRADE CANDIDATE"?"checkmark-circle-outline":"close-circle-outline"} size={16} color={deep.decision==="TRADE CANDIDATE"?colors.green:colors.red}/><Text style={s.reasonText}>{x}</Text></View>)}
      <Text style={s.sub}>Recent range: {intel.levels?.recent_low??"—"} → {intel.levels?.recent_high??"—"} · Position {intel.price_position_pct??"—"}%</Text>
    </Panel>:null}

    {!loading&&report?<Panel>
      <View style={s.reportHead}><View><Text style={s.label}>HISTORICAL VALIDATION</Text><Text style={s.status}>{report.status==="ok"?"COMPLETED":(report.status??"UNKNOWN").replace("_"," ").toUpperCase()}</Text></View><Text style={s.safeText}>NO EXECUTION</Text></View>
      <Text style={s.sub}>Lookahead safe · 1H → 15M → 5M · cost {report.cost_r??0}R per trade</Text>
      <View style={s.grid}>
        <Metric label="TRADES" value={metricValue(report.trades,0)}/>
        <Metric label="WIN RATE" value={report.win_rate!=null?report.win_rate+"%":"—"}/>
        <Metric label="EXPECTANCY" value={report.expectancy_r!=null?report.expectancy_r+" R":"—"}/>
        <Metric label="TOTAL R" value={report.total_r!=null?report.total_r+" R":"—"}/>
        <Metric label="PROFIT FACTOR" value={report.profit_factor??"—"}/>
        <Metric label="MAX DD" value={report.max_drawdown_r!=null?report.max_drawdown_r+" R":"—"}/>
        <Metric label="MAX LOSS STREAK" value={metricValue(report.max_consecutive_losses,0)}/>
        <Metric label="AMBIGUOUS" value={metricValue(report.ambiguous_bars,0)}/>
      </View>
      {(assessment.notes||[]).map((x:string,i:number)=><Text key={i} style={s.noteLine}>• {x}</Text>)}
      {report.trades_sample?.length?<View style={{marginTop:10}}>{report.trades_sample.slice(-6).reverse().map((t:any,i:number)=><View key={i} style={s.tradeRow}><View style={{flex:1}}><Text style={s.tradeSide}>{t.signal} · {t.outcome}</Text><Text style={s.sub}>Entry {t.entry} · Exit {t.exit}</Text></View><Text style={[s.rValue,{color:Number(t.r)>=0?colors.green:colors.red}]}>{Number(t.r)>0?"+":""}{t.r}R</Text></View>)}</View>:null}
    </Panel>:null}

    {journalStats?<Panel><Text style={s.section}>YOUR TRADE JOURNAL</Text><View style={s.grid}><Metric label="ENTRIES" value={journalStats.entries}/><Metric label="WIN RATE" value={journalStats.win_rate+"%"}/><Metric label="TOTAL P/L" value={journalStats.total_pnl}/><Metric label="TOTAL R" value={journalStats.total_r}/></View></Panel>:null}

    {!loading&&live?.intelligence?.rules?<Panel><Text style={s.section}>ACTIVE STRATEGY RULES</Text><Text style={s.rule}>{live.intelligence.rules.name}</Text><Text style={s.sub}>Regime: {live.intelligence.rules.regime}</Text><Text style={s.sub}>Setup: {live.intelligence.rules.setup}</Text><Text style={s.sub}>Trigger: {live.intelligence.rules.trigger}</Text><Text style={s.sub}>Protection: {live.intelligence.rules.protection}</Text></Panel>:null}

    <Panel><View style={s.note}><Ionicons name="information-circle-outline" size={18} color={colors.green}/><Text style={s.noteText}>Historical validation is evidence, not a promise. Results should be checked across symbols, market regimes, costs and fresh out-of-sample periods.</Text></View></Panel>
    <Pressable disabled={loading} style={[s.refresh,loading&&{opacity:0.55}]} onPress={run}><Ionicons name="refresh-outline" size={18} color={colors.white}/><Text style={s.refreshText}>{loading?"ANALYSIS IN PROGRESS…":"RUN FULL ANALYSIS AGAIN"}</Text></Pressable>
  </ScrollView>
}

const s=StyleSheet.create({
 screen:{flex:1,backgroundColor:colors.background},c:{padding:18,paddingTop:58,paddingBottom:112,gap:14},
 header:{flexDirection:"row",justifyContent:"space-between",alignItems:"center"},
 terminalBar:{flexDirection:"row",alignItems:"center",gap:9,paddingHorizontal:12,paddingVertical:10,borderRadius:11,backgroundColor:colors.surface2,borderWidth:1,borderColor:colors.border},terminalStatus:{flexDirection:"row",alignItems:"center",gap:6},terminalDot:{width:6,height:6,borderRadius:6,backgroundColor:colors.green},terminalText:{color:colors.green,fontSize:8,fontWeight:"900",letterSpacing:.8},terminalDivider:{width:1,height:15,backgroundColor:colors.border},terminalLock:{color:colors.muted,fontSize:7,fontWeight:"900",letterSpacing:.5,flexShrink:1},
 eyebrow:{color:colors.green,fontSize:9,fontWeight:"900",letterSpacing:1.2},title:{color:colors.text,fontSize:26,fontWeight:"900",marginTop:3},sub:{color:colors.muted,fontSize:11,lineHeight:16,marginTop:4},icon:{width:46,height:46,borderRadius:14,backgroundColor:"#09271b",borderWidth:1,borderColor:"#1b513a",alignItems:"center",justifyContent:"center"},
 label:{color:colors.muted,fontSize:8,fontWeight:"900",letterSpacing:1.1},chips:{gap:8,paddingTop:10},chip:{paddingHorizontal:12,paddingVertical:9,borderRadius:10,borderWidth:1,borderColor:colors.border,backgroundColor:colors.surface2},chipActive:{borderColor:"#1b6a48",backgroundColor:"#09271b"},chipText:{color:colors.muted,fontSize:10,fontWeight:"900"},chipTextActive:{color:colors.green},
 costRow:{flexDirection:"row",alignItems:"center",gap:10,marginTop:16},input:{width:64,borderWidth:1,borderColor:colors.border,borderRadius:9,color:colors.text,paddingHorizontal:9,paddingVertical:8,textAlign:"center"},
 loading:{alignItems:"center",gap:9,paddingVertical:8},error:{flexDirection:"row",gap:8,alignItems:"center"},errorText:{color:"#ffb5bf",fontSize:11,flex:1},
 reportHead:{flexDirection:"row",justifyContent:"space-between",alignItems:"center"},status:{color:colors.text,fontSize:17,fontWeight:"900",marginTop:3},safeText:{color:colors.green,fontSize:8,fontWeight:"900"},livePill:{flexDirection:"row",alignItems:"center",gap:5},dot:{width:7,height:7,borderRadius:7,backgroundColor:colors.green},
 decisionHero:{flexDirection:"row",alignItems:"center",gap:14},
 heroDecision:{fontSize:22,fontWeight:"900",marginTop:4},
 heroReason:{color:colors.muted,fontSize:10,lineHeight:15,marginTop:5},
 scoreRing:{width:72,height:72,borderRadius:72,borderWidth:2,borderColor:colors.borderGlow,backgroundColor:colors.surface2,alignItems:"center",justifyContent:"center",...shadows.glow},
 scoreNumber:{color:colors.text,fontSize:25,fontWeight:"900"},scoreCaption:{color:colors.muted,fontSize:7,fontWeight:"900"},
 confidenceBar:{height:5,borderRadius:5,backgroundColor:colors.surface3,overflow:"hidden",marginTop:14},confidenceFill:{height:5,borderRadius:5},
 reason:{color:colors.text,fontSize:11,lineHeight:17,marginTop:10},deepDecision:{fontSize:11,fontWeight:"900",marginTop:5},grid:{flexDirection:"row",flexWrap:"wrap",marginTop:12,borderTopWidth:1,borderTopColor:colors.border},metric:{width:"50%",paddingTop:12,paddingBottom:3,backgroundColor:colors.surface2,paddingHorizontal:10,borderRadius:10,marginBottom:4},metricLabel:{color:colors.muted,fontSize:8,fontWeight:"800",letterSpacing:.8},metricValue:{color:colors.text,fontSize:16,fontWeight:"900",marginTop:4},
 section:{color:colors.green,fontSize:9,fontWeight:"900",letterSpacing:1.1,marginBottom:7},reasonRow:{flexDirection:"row",gap:8,paddingVertical:7,borderTopWidth:1,borderTopColor:colors.border},reasonText:{color:colors.text,fontSize:11,flex:1,lineHeight:15},noteLine:{color:colors.muted,fontSize:10,lineHeight:15,marginTop:6},tradeRow:{flexDirection:"row",alignItems:"center",paddingVertical:9,borderTopWidth:1,borderTopColor:colors.border},tradeSide:{color:colors.text,fontSize:11,fontWeight:"900"},rValue:{fontSize:15,fontWeight:"900"},
 rule:{color:colors.text,fontSize:11,fontWeight:"900",marginBottom:5},
 note:{flexDirection:"row",gap:8},noteText:{color:colors.muted,fontSize:10,lineHeight:15,flex:1},refresh:{height:48,borderRadius:13,backgroundColor:"#123e2b",alignItems:"center",justifyContent:"center",flexDirection:"row",gap:8},refreshText:{color:colors.white,fontSize:10,fontWeight:"900",letterSpacing:.7}
});
