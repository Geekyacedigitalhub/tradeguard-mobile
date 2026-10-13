import {ScrollView,StyleSheet,Text,View,ActivityIndicator,Pressable,AppState} from "react-native";
import {useEffect,useState} from "react";
import {Panel} from "../../src/components/Panel";
import {colors,radii,shadows} from "../../src/theme";
import {api} from "../../src/api";

function Metric({label,value}:{label:string;value:string|number}) {
  return <View style={s.metric}>
    <Text style={s.metricLabel}>{label}</Text>
    <Text style={s.metricValue}>{value}</Text>
  </View>;
}

function QualityRow({label,value}:{label:string;value:string}) {
  const positive=["BULLISH","BEARISH","BREAK","ACCEPTABLE","NEAR VALUE"];
  const negative=["CONFLICT","NOT ALIGNED","OUTSIDE RANGE","STRETCHED","NOT CONFIRMED"];
  const valueColor=positive.includes(value)
    ? colors.green
    : negative.includes(value)
      ? colors.red
      : colors.text;

  return <View style={s.qualityRow}>
    <Text style={s.qualityLabel}>{label}</Text>
    <Text style={[s.qualityValue,{color:valueColor}]}>{value}</Text>
  </View>;
}


function PriceChart({symbol,entry,stopLoss,takeProfit,support,resistance}:{symbol:string;entry:number;stopLoss:number;takeProfit:number;support:number;resistance:number}){
  const [interval,setIntervalValue]=useState<"5m"|"15m"|"1h">("5m");
  const [candles,setCandles]=useState<any[]>([]);
  const [livePrice,setLivePrice]=useState<number|null>(null);
  const [streamState,setStreamState]=useState<"LIVE"|"RECONNECTING"|"OFFLINE">("RECONNECTING");
  const [lastTickAt,setLastTickAt]=useState<number|null>(null);
  const [resumeKey,setResumeKey]=useState(0);

  useEffect(()=>{
    let mounted=true;
    let refreshInFlight=false;
    let refreshQueued=false;
    const load=async()=>{
      if(refreshInFlight){
        refreshQueued=true;
        return;
      }
      refreshInFlight=true;
      try{
        const data=await api.marketCandles(symbol,interval,80);
        if(mounted)setCandles(Array.isArray(data?.candles)?data.candles:[]);
      }catch{
        // Preserve the last successful candles during transient network failures.
        // An empty chart should mean no data has arrived yet, not a brief outage.
      }finally{
        refreshInFlight=false;
        if(mounted&&refreshQueued){
          refreshQueued=false;
          void load();
        }
      }
    };
    load();
    const timer=setInterval(load,60000);
    return()=>{
      mounted=false;
      refreshQueued=false;
      clearInterval(timer);
    };
  },[symbol,interval]);

  useEffect(()=>{
    const subscribedAt=Date.now();
    const freshnessTimer=setInterval(()=>{
      setLastTickAt(last=>{
        if((last===null&&Date.now()-subscribedAt>45000)||(last!==null&&Date.now()-last>45000)){
          setStreamState("OFFLINE");
        }
        return last;
      });
    },5000);
    return()=>clearInterval(freshnessTimer);
  },[]);

  useEffect(()=>{
    const stateSubscription=AppState.addEventListener("change",state=>{
      if(state==="active"){
        setStreamState("RECONNECTING");
        setResumeKey(value=>value+1);
      }
    });
    return()=>stateSubscription.remove();
  },[]);

  useEffect(()=>{
    let mounted=true;
    let closeStream:()=>void=()=>{};

    api.marketStream((tick:any)=>{
      if(!mounted||String(tick?.symbol??"").toUpperCase().replace(/[^A-Z0-9]/g,"")!==symbol.toUpperCase().replace(/[^A-Z0-9]/g,""))return;
      const price=Number(tick.price);
      const tickTime=Number(tick.time_msc||tick.time||0);
      if(!Number.isFinite(price)||price<=0||!tickTime)return;
      setLivePrice(price);
      setLastTickAt(Date.now());
      const seconds=interval==="5m"?300:interval==="15m"?900:3600;
      const timeSeconds=Math.floor((tickTime>100000000000?tickTime/1000:tickTime)/seconds)*seconds;
      setCandles(prev=>{
        if(!prev.length)return prev;
        const next=[...prev];
        const last=next[next.length-1];
        const lastTime=Number(last.time||0);
        if(lastTime===timeSeconds){
          next[next.length-1]={...last,high:Math.max(Number(last.high),price),low:Math.min(Number(last.low),price),close:price};
        }else if(timeSeconds>lastTime){
          next.push({time:timeSeconds,open:price,high:price,low:price,close:price,volume:0});
          while(next.length>80)next.shift();
        }
        return next;
      });
    },state=>{
      if(mounted)setStreamState(state);
    },symbol).then(close=>{ closeStream=close; if(!mounted)close(); });

    return()=>{
      mounted=false;
      closeStream();
    };
  },[symbol,interval,resumeKey]);

  const closes=candles.map(c=>Number(c.close)).filter(Number.isFinite);
  if(livePrice!=null)closes.push(livePrice);
  const min=closes.length?Math.min(...closes):0;
  const max=closes.length?Math.max(...closes):0;
  const range=max-min||1;
  const points=candles.slice(-60);
  const height=180;
  const levelY=(value:number)=>range?Math.max(0,Math.min(height,(1-(value-min)/range)*height)):height/2;

  return <View style={s.chartWrap}>
    <View style={s.chartHeader}>
      <View style={{flexDirection:"row",alignItems:"center",gap:7}}>
        <Text style={s.chartTitle}>PRICE CHART</Text>
        <Text style={[s.liveBadge,{color:streamState==="LIVE"?colors.green:streamState==="RECONNECTING"?"#f2c94c":colors.red}]}>● {streamState}</Text>
      </View>
      <View style={s.intervalRow}>
        {(["5m","15m","1h"] as const).map(v=><Pressable key={v} onPress={()=>setIntervalValue(v)} style={[s.intervalButton,interval===v&&s.intervalActive]}><Text style={[s.intervalText,interval===v&&s.intervalTextActive]}>{v.toUpperCase()}</Text></Pressable>)}
      </View>
    </View>
    {points.length<2
      ? <View style={s.chartEmpty}><ActivityIndicator color={colors.green}/><Text style={s.chartEmptyText}>Loading price data...</Text></View>
      : <View style={s.chart}>
          <View style={s.chartGrid}/>
          {livePrice!=null&&<View style={[s.livePriceLine,{top:levelY(livePrice)}]}><Text style={s.livePriceText}>{livePrice.toFixed(5)}</Text></View>}
          {entry>0&&<View style={[s.levelLine,{top:levelY(entry)}]}><Text style={s.levelText}>ENTRY {entry.toFixed(2)}</Text></View>}
          {stopLoss>0&&<View style={[s.levelLine,s.slLine,{top:levelY(stopLoss)}]}><Text style={s.levelText}>SL {stopLoss.toFixed(2)}</Text></View>}
          {takeProfit>0&&<View style={[s.levelLine,s.tpLine,{top:levelY(takeProfit)}]}><Text style={s.levelText}>TP {takeProfit.toFixed(2)}</Text></View>}
          {support>0&&<View style={[s.levelLine,s.supportLine,{top:levelY(support)}]}><Text style={s.levelText}>SUP {support.toFixed(2)}</Text></View>}
          {resistance>0&&<View style={[s.levelLine,s.resistanceLine,{top:levelY(resistance)}]}><Text style={s.levelText}>RES {resistance.toFixed(2)}</Text></View>}
          {points.map((c,index)=>{
            const open=Number(c.open), close=Number(c.close), high=Number(c.high), low=Number(c.low);
            const x=index/Math.max(points.length,1)*100;
            const bodyTop=levelY(Math.max(open,close));
            const bodyHeight=Math.max(2,Math.abs(levelY(open)-levelY(close)));
            const wickTop=levelY(high); const wickHeight=Math.max(1,levelY(low)-wickTop);
            const bullish=close>=open;
            return <View key={"c"+index} style={[s.candle,{left:`${x}%`,width:`${100/60}%` as `${number}%`}]}>
              <View style={[s.wick,{top:wickTop,height:wickHeight}]}/>
              <View style={[s.body,{top:bodyTop,height:bodyHeight,backgroundColor:bullish?colors.green:colors.red}]}/>
            </View>;
          })}
          <View style={s.chartLabels}><Text style={s.chartLabel}>{min.toFixed(2)}</Text><Text style={s.chartLabel}>{max.toFixed(2)}</Text></View>
        </View>}
  </View>;
}

function ProfitEngineCard({row}:{row:any}) {
  const p=row.profit_engine||{}; const learning=p.learning||{}; const optimizer=p.optimizer||{}; const signalQualified=p.decision==="EXECUTE";
  const learningColor=learning.status==="PROMOTE"?colors.green:learning.status==="DEMOTE"?colors.red:learning.status==="CAUTION"?"#f2c94c":colors.text;
  const optimizerColor=optimizer.status==="PROMOTE"?colors.green:optimizer.status==="DEMOTE"?colors.red:optimizer.status==="CAUTION"?"#f2c94c":colors.text;
  return <View style={s.profitCard}>
    <View style={s.profitHeader}><View><Text style={s.liveTitle}>PROFIT ENGINE</Text><Text style={s.profitTier}>{p.tier||"REJECT"} · {signalQualified?"SIGNAL QUALIFIED · ENTRY BLOCKED":"WAIT · ENTRY BLOCKED"}</Text></View><View style={s.edgeBox}><Text style={s.edgeValue}>{p.edge_score!=null?Number(p.edge_score).toFixed(1):"—"}</Text><Text style={s.edgeLabel}>EDGE</Text></View></View>
    <View style={s.grid}>
      <Metric label="EXPECTANCY" value={p.expectancy_r!=null?Number(p.expectancy_r).toFixed(2)+"R":"—"}/><Metric label="REWARD / RISK" value={p.reward_risk!=null?Number(p.reward_risk).toFixed(2)+"R":"—"}/>
      <Metric label="PROFIT FACTOR" value={p.profit_factor!=null?Number(p.profit_factor).toFixed(2):"—"}/><Metric label="HIST. TRADES" value={p.historical_trades??0}/>
      <Metric label="RISK MULT." value={p.risk_multiplier!=null?Number(p.risk_multiplier).toFixed(2)+"x":"—"}/><Metric label="COST" value={p.estimated_cost_r!=null?Number(p.estimated_cost_r).toFixed(2)+"R":"—"}/>
    </View>
    <View style={s.learningRow}><Text style={s.qualityLabel}>LIVE LEARNING</Text><Text style={[s.learningValue,{color:learningColor}]}>{learning.status||"LEARNING"} · {learning.metrics?.trades??0} trades</Text></View>
    {learning.reason&&<Text style={s.intelWhy}>{learning.reason}</Text>}
    <View style={s.learningRow}><Text style={s.qualityLabel}>ADAPTIVE OPTIMIZER</Text><Text style={[s.learningValue,{color:optimizerColor}]}>{optimizer.status||"INSUFFICIENT"} · {optimizer.metrics?.trades??0} trades</Text></View>
    {optimizer.reason&&<Text style={s.intelWhy}>{optimizer.reason}</Text>}
    {(p.vetoes||[]).slice(0,2).map((v:string,i:number)=><Text key={"v"+i} style={s.veto}>• {v}</Text>)}
  </View>;
}

function reasonValue(reason:string,label:string,positive:string,negative:string){
  if(reason.includes(positive)) return positive;
  if(reason.includes(negative)) return negative;
  return negative;
}

export default function Markets(){
  const [rows,setRows]=useState<any[]|null>(null);
  const [message,setMessage]=useState("");
  const [scannerStale,setScannerStale]=useState(false);
  const [scannerUpdatedAt,setScannerUpdatedAt]=useState<number|null>(null);

  useEffect(()=>{
    let mounted=true;
    let refreshInFlight=false;
    let refreshQueued=false;
    const load=async()=>{
      if(refreshInFlight){
        refreshQueued=true;
        return;
      }
      refreshInFlight=true;
      try{
        const data=await api.markets();
        if(!Array.isArray(data))throw new Error("Market scanner returned an invalid payload");
        if(mounted){
          setRows(data);
          setScannerStale(false);
          setScannerUpdatedAt(Date.now());
        }
      }catch{
        // Preserve the last successful snapshot but clearly mark it stale.
        if(mounted)setScannerStale(true);
      }finally{
        refreshInFlight=false;
        if(mounted&&refreshQueued){
          refreshQueued=false;
          void load();
        }
      }
    };
    load();
    // The backend keeps a 60s scanner cache. Match that cadence so multiple
    // mounted screens do not repeatedly download the same 14-market payload.
    const timer=setInterval(load,60000);
    const appStateSubscription=AppState.addEventListener("change",state=>{
      if(state==="active")void load();
    });
    return()=>{
      mounted=false;
      refreshQueued=false;
      clearInterval(timer);
      appStateSubscription.remove();
    };
  },[]);

  const focus=rows?.find(r=>r.signal==="BUY"||r.signal==="SELL");
  return <ScrollView style={s.screen} contentContainerStyle={s.c}>
    <View style={s.header}>
      <View style={{flex:1}}><Text style={s.eyebrow}>TRADEGUARD / MARKET DESK</Text><Text style={s.title}>Market Terminal</Text><Text style={s.sub}>Live prices · multi-timeframe intelligence · entries gated pending verified broker sizing</Text></View>
      <View style={s.liveChip}><View style={[s.liveDot,{backgroundColor:scannerStale?colors.red:colors.green}]}/><Text style={[s.liveChipText,{color:scannerStale?colors.red:colors.green}]}>{scannerStale?"SCANNER STALE":rows===null?"CONNECTING":rows.length===0?"NO MARKET DATA":"SCANNER READY"}</Text></View>
    </View>
    {scannerUpdatedAt!==null&&<Text style={s.sub}>Scanner updated {new Date(scannerUpdatedAt).toLocaleTimeString()} · {scannerStale?"refresh failed; showing last successful snapshot":"refresh available"}</Text>}
    <View style={s.watchHeader}><Text style={s.watchHeading}>MARKET WATCHLIST</Text><Text style={s.watchCount}>{rows===null?"—":rows.length} INSTRUMENTS</Text></View>
    <View style={s.watchRow}>
      {(rows??[]).slice(0,5).map((r:any)=>{
        const c=r.signal==="BUY"?colors.green:r.signal==="SELL"?colors.red:colors.muted;
        return <View key={r.symbol} style={s.watchItem}><Text style={s.watchSymbol}>{r.symbol}</Text><Text style={[s.watchSignal,{color:c}]}>{r.signal??"NO TRADE"} {r.score==null||r.score===""||!Number.isFinite(Number(r.score))?"—":Number(r.score).toLocaleString(undefined,{maximumFractionDigits:1})}</Text></View>;
      })}
    </View>
    {focus&&<Panel>
      <View style={s.focusTop}><View><Text style={s.label}>TOP SETUP</Text><Text style={s.focusSymbol}>{focus.symbol}</Text></View><View style={s.focusScore}><Text style={[s.focusScoreValue,{color:focus.signal==="BUY"?colors.green:colors.red}]}>{focus.score==null||focus.score===""||!Number.isFinite(Number(focus.score))?"—":Number(focus.score).toLocaleString(undefined,{maximumFractionDigits:1})}</Text><Text style={s.focusScoreLabel}>SIGNAL</Text></View></View>
      <View style={s.focusBar}><View style={[s.focusBarFill,{width:`${focus.score==null||focus.score===""||!Number.isFinite(Number(focus.score))?0:Math.max(0,Math.min(100,Number(focus.score)))}%`,backgroundColor:focus.signal==="BUY"?colors.green:focus.signal==="SELL"?colors.red:colors.muted}]}/></View>
      <Text style={s.focusReason}>{focus.deep_analysis?.decision??"NO TRADE"} · {focus.intelligence?.regime??"UNKNOWN"} regime · {focus.intelligence?.session??"UNKNOWN"} session</Text>
    </Panel>}

    {message!==""&&<Panel><Text style={s.message}>{message}</Text></Panel>}

    {rows===null
      ? <ActivityIndicator color={colors.green}/>
      : rows.map(r=>{
        const i=r.indicators||{};
        const tf=r.timeframes||{};
        const current=Number(r.entry||0);
        const h1Rsi=Number(i.h1_rsi||0);
        const m15Rsi=Number(i.m15_rsi||0);
        const m5Rsi=Number(i.m5_rsi||0);
        const m5Atr=Number(i.m5_atr||0);
        const trigger=r.entry_trigger==="5m_breakout"?"CONFIRMED":"WAITING";
        const direction=tf["1h"]||"NEUTRAL";
        const setup=tf["15m"]||"NO TRADE";
        const entryTf=tf["5m"]||"NEUTRAL";
        const intel=r.intelligence||{};
        const deep=r.deep_analysis||{};
        const deepDecision=deep.decision||"NO TRADE";

        return <Panel key={r.symbol}>
          <View style={s.row}>
            <View style={{flex:1}}>
              <Text style={s.symbol}>{r.symbol}</Text>
              <Text style={s.feed}>CLOUD MTF · 1H → 15M → 5M</Text>
            </View>
            <View style={s.signalBlock}>
              <Text style={[s.score,{color:r.signal==="BUY"?colors.green:r.signal==="SELL"?colors.red:colors.muted}]}>{r.score}</Text>
              <Text style={s.sig}>{r.signal}</Text>
            </View>

            {(r.signal==="BUY"||r.signal==="SELL")&&deepDecision==="TRADE CANDIDATE"&&
              <Pressable disabled style={[s.approve,{opacity:0.5}]}>
                <Text style={s.approveText}>ENTRY GATE CLOSED</Text>
              </Pressable>}
          </View>

          <View style={s.divider}/><PriceChart symbol={r.symbol} entry={Number(r.entry||0)} stopLoss={Number(r.stop_loss||0)} takeProfit={Number(r.take_profit||0)} support={Number(deep.timeframes?.["15m"]?.structure?.support||0)} resistance={Number(deep.timeframes?.["15m"]?.structure?.resistance||0)}/>

          <Text style={s.sectionTitle}>SIGNAL QUALITY</Text>
          <View style={s.qualityCard}>
            <QualityRow label="1H Direction" value={direction}/>
            <QualityRow label="15M Setup" value={setup}/>
            <QualityRow label="5M Direction" value={entryTf}/>
            <QualityRow label="Entry Trigger" value={trigger}/>
            <QualityRow label="Risk / Reward" value={r.profit_engine?.reward_risk!=null?"1 : "+Number(r.profit_engine.reward_risk).toFixed(2):"—"}/>
          </View>

          <ProfitEngineCard row={r}/>

          <Text style={s.liveTitle}>DEEP RESEARCH GATE</Text><Text style={[s.deepDecision,{color:deepDecision==="TRADE CANDIDATE"?colors.green:deepDecision==="WAIT"?"#f2c94c":colors.red}]}>{deepDecision} · {deep.confluence??0}/100</Text><Text style={s.intelWhy}>{(deep.reasons||[]).slice(0,3).join(" · ")}</Text><Text style={s.liveTitle}>MARKET INTELLIGENCE</Text><Text style={s.intel}>{intel.regime||"UNKNOWN"} · {intel.session||"UNKNOWN"} · Range {intel.price_position_pct??"—"}%</Text><Text style={s.intelWhy}>{(intel.why_not_trade||[]).slice(0,2).join(" · ")}</Text><Text style={s.liveTitle}>INDICATOR EVIDENCE · 5M</Text><View style={s.grid}><Metric label="EMA 20" value={deep.timeframes?.["5m"]?.analysis?.indicators?.ema20!=null?Number(deep.timeframes["5m"].analysis.indicators.ema20).toFixed(5):"—"}/><Metric label="EMA 50" value={deep.timeframes?.["5m"]?.analysis?.indicators?.ema50!=null?Number(deep.timeframes["5m"].analysis.indicators.ema50).toFixed(5):"—"}/><Metric label="RSI 14" value={deep.timeframes?.["5m"]?.analysis?.indicators?.rsi14!=null?Number(deep.timeframes["5m"].analysis.indicators.rsi14).toFixed(2):"—"}/><Metric label="MACD" value={deep.timeframes?.["5m"]?.analysis?.indicators?.macd!=null?Number(deep.timeframes["5m"].analysis.indicators.macd).toFixed(5):"—"}/><Metric label="ADX 14" value={deep.timeframes?.["5m"]?.regime?.adx!=null?Number(deep.timeframes["5m"].regime.adx).toFixed(2):"—"}/><Metric label="STOCH 14" value={deep.timeframes?.["5m"]?.analysis?.indicators?.stochastic14!=null?Number(deep.timeframes["5m"].analysis.indicators.stochastic14).toFixed(2):"—"}/><Metric label="CCI 20" value={deep.timeframes?.["5m"]?.analysis?.indicators?.cci20!=null?Number(deep.timeframes["5m"].analysis.indicators.cci20).toFixed(2):"—"}/><Metric label="ATR 14" value={deep.timeframes?.["5m"]?.analysis?.indicators?.atr14!=null?Number(deep.timeframes["5m"].analysis.indicators.atr14).toFixed(5):"—"}/></View><Text style={s.intel}>Candles: {(deep.timeframes?.["5m"]?.analysis?.candles||[]).slice(-1)[0]||"—"} · Structure: {deep.timeframes?.["5m"]?.structure?.state||"UNKNOWN"} · Sweep: {deep.timeframes?.["5m"]?.structure?.sweep||"NONE"}</Text><Text style={s.liveTitle}>MULTI-TIMEFRAME DATA</Text>
          <View style={s.grid}>
            <Metric label="ENTRY" value={current?current.toFixed(5):"—"}/>
            <Metric label="1H RSI" value={h1Rsi?h1Rsi.toFixed(1):"—"}/>
            <Metric label="15M RSI" value={m15Rsi?m15Rsi.toFixed(1):"—"}/>
            <Metric label="5M RSI" value={m5Rsi?m5Rsi.toFixed(1):"—"}/>
            <Metric label="5M ATR" value={m5Atr?m5Atr.toFixed(5):"—"}/>
            <Metric label="TRIGGER" value={trigger}/>
          </View>
        </Panel>;
      })}
  </ScrollView>;
}

const s=StyleSheet.create({
  screen:{flex:1,backgroundColor:colors.background},
  c:{padding:18,paddingTop:58,paddingBottom:112,gap:14},
  header:{flexDirection:"row",justifyContent:"space-between",alignItems:"flex-start",gap:10},
  eyebrow:{color:colors.green,fontSize:8,fontWeight:"900",letterSpacing:1.6},
  title:{color:colors.text,fontSize:28,fontWeight:"900",marginTop:3},
  sub:{color:colors.muted,fontSize:10,marginTop:4},
  liveChip:{flexDirection:"row",alignItems:"center",gap:5,borderWidth:1,borderColor:colors.borderGlow,backgroundColor:"#08261a",paddingHorizontal:9,paddingVertical:7,borderRadius:radii.pill},
  liveDot:{width:6,height:6,borderRadius:6,backgroundColor:colors.green},
  liveChipText:{color:colors.green,fontSize:8,fontWeight:"900",letterSpacing:1},
  watchHeader:{flexDirection:"row",justifyContent:"space-between",alignItems:"center",marginTop:2},watchHeading:{color:colors.text,fontSize:11,fontWeight:"900",letterSpacing:1},watchCount:{color:colors.muted,fontSize:8,fontWeight:"900",letterSpacing:.8},
 watchRow:{flexDirection:"row",gap:7},
  watchItem:{flex:1,minWidth:58,padding:8,borderRadius:11,backgroundColor:colors.surface2,borderWidth:1,borderColor:colors.border},
  watchSymbol:{color:colors.text,fontSize:9,fontWeight:"900"},
  watchSignal:{fontSize:7,fontWeight:"900",marginTop:4},
  label:{color:colors.muted,fontSize:8,fontWeight:"900",letterSpacing:1.2},
  focusTop:{flexDirection:"row",justifyContent:"space-between",alignItems:"center"},
  focusSymbol:{color:colors.text,fontSize:22,fontWeight:"900",marginTop:4},
  focusScore:{alignItems:"flex-end"},
  focusScoreValue:{fontSize:26,fontWeight:"900"},
  focusScoreLabel:{color:colors.muted,fontSize:7,fontWeight:"900",letterSpacing:1},
  focusBar:{height:6,borderRadius:6,backgroundColor:colors.surface3,overflow:"hidden",marginTop:14},
  focusBarFill:{height:6,borderRadius:6},
  focusReason:{color:colors.muted,fontSize:9,fontWeight:"700",marginTop:8},
  row:{flexDirection:"row",alignItems:"center",gap:12},
  symbol:{color:colors.text,fontSize:16,fontWeight:"800"},
  feed:{color:colors.muted,fontSize:9,fontWeight:"800",letterSpacing:1,marginTop:4},
  signalBlock:{alignItems:"flex-end",minWidth:62},
  score:{fontSize:24,fontWeight:"900"},
  sig:{color:colors.text,fontSize:10,fontWeight:"900",marginTop:2},
  approve:{backgroundColor:colors.green,paddingHorizontal:10,paddingVertical:8,borderRadius:8},
  approveText:{color:colors.background,fontSize:10,fontWeight:"900"},
  message:{color:colors.text,fontSize:12,fontWeight:"700"},
  divider:{height:1,backgroundColor:colors.border,marginTop:14,marginBottom:12},
  sectionTitle:{color:colors.text,fontSize:11,fontWeight:"900",letterSpacing:1,marginBottom:7},
  qualityCard:{backgroundColor:colors.panel,borderRadius:10,paddingHorizontal:11,paddingVertical:3,marginBottom:14},
  qualityRow:{flexDirection:"row",justifyContent:"space-between",alignItems:"center",paddingVertical:8,borderBottomWidth:1,borderBottomColor:colors.border},
  qualityLabel:{color:colors.muted,fontSize:11,fontWeight:"700"},
  qualityValue:{fontSize:10,fontWeight:"900"},
  liveTitle:{color:colors.green,fontSize:11,fontWeight:"900",letterSpacing:1},
  deepDecision:{fontSize:11,fontWeight:"900",marginTop:5},
  intel:{color:colors.text,fontSize:11,fontWeight:"900",marginTop:6},intelWhy:{color:colors.muted,fontSize:10,lineHeight:14,marginTop:4},
  grid:{flexDirection:"row",flexWrap:"wrap",gap:8,marginTop:9},
  metric:{width:"31%",minWidth:92,backgroundColor:colors.panel,borderRadius:8,padding:9},
  metricLabel:{color:colors.muted,fontSize:8,fontWeight:"800"},
  metricValue:{color:colors.text,fontSize:11,fontWeight:"900",marginTop:4},
  profitCard:{backgroundColor:colors.surface2,borderRadius:radii.md,padding:11,marginBottom:14,borderWidth:1,borderColor:colors.borderGlow},
  profitHeader:{flexDirection:"row",justifyContent:"space-between",alignItems:"center"},
  profitTier:{color:colors.text,fontSize:11,fontWeight:"900",marginTop:4},
  edgeBox:{alignItems:"flex-end"},
  edgeValue:{color:colors.green,fontSize:24,fontWeight:"900"},
  edgeLabel:{color:colors.muted,fontSize:7,fontWeight:"900",letterSpacing:1},
  learningRow:{flexDirection:"row",justifyContent:"space-between",alignItems:"center",marginTop:9,paddingTop:9,borderTopWidth:1,borderTopColor:colors.border},
  learningValue:{fontSize:9,fontWeight:"900"},
  veto:{color:"#f2c94c",fontSize:9,lineHeight:13,marginTop:3},

  chartWrap:{marginBottom:14,backgroundColor:colors.surface2,borderRadius:radii.md,padding:10,borderWidth:1,borderColor:colors.border,...shadows.card},
  chartHeader:{flexDirection:"row",justifyContent:"space-between",alignItems:"center",marginBottom:8},
  chartTitle:{color:colors.text,fontSize:10,fontWeight:"900",letterSpacing:1},
  liveBadge:{fontSize:7,fontWeight:"900",letterSpacing:0.5},
  livePriceLine:{position:"absolute",left:0,right:0,height:1,borderTopWidth:1,borderTopColor:colors.green,borderStyle:"dashed"},
  livePriceText:{position:"absolute",right:5,top:-11,color:colors.green,fontSize:7,fontWeight:"900"},
  intervalRow:{flexDirection:"row",gap:5},
  intervalButton:{paddingHorizontal:7,paddingVertical:5,borderRadius:6,backgroundColor:colors.panel},
  intervalActive:{backgroundColor:colors.green},
  intervalText:{color:colors.muted,fontSize:8,fontWeight:"900"},
  intervalTextActive:{color:colors.background},
  chartEmpty:{height:180,alignItems:"center",justifyContent:"center",gap:8,backgroundColor:colors.panel,borderRadius:10},
  chartEmptyText:{color:colors.muted,fontSize:10},
  chart:{height:180,backgroundColor:colors.panel,borderRadius:10,overflow:"hidden",position:"relative"},
  chartGrid:{position:"absolute",left:0,right:0,top:"50%",height:1,backgroundColor:colors.border},
  levelLine:{position:"absolute",left:0,right:0,height:1,backgroundColor:colors.text,opacity:0.65},
  slLine:{backgroundColor:colors.red},
  tpLine:{backgroundColor:colors.green},
  supportLine:{backgroundColor:"#f2c94c",opacity:0.55},
  resistanceLine:{backgroundColor:"#f2c94c",opacity:0.55},
  levelText:{position:"absolute",right:5,top:-10,color:colors.text,fontSize:7,fontWeight:"900"},
  candle:{position:"absolute",top:0,bottom:0,alignItems:"center"},
  wick:{position:"absolute",width:1,backgroundColor:colors.muted},
  body:{position:"absolute",width:"65%",minHeight:2,borderRadius:1},
  chartLabels:{position:"absolute",left:5,right:5,top:5,bottom:5,justifyContent:"space-between"},
  chartLabel:{color:colors.muted,fontSize:8,fontWeight:"700"}
});