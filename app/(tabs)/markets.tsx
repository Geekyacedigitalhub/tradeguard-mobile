import {ScrollView,StyleSheet,Text,View,ActivityIndicator,Pressable} from "react-native";
import {useEffect,useState} from "react";
import {Panel} from "../../src/components/Panel";
import {colors} from "../../src/theme";
import {api} from "../../src/api";

async function waitForCommand(id:number,setMessage:(v:string)=>void){
  for(let i=0;i<20;i++){
    const status=await api.bridgeCommand(id);
    if(status.status==="completed"){
      const ticket=status.result?.ticket;
      setMessage(ticket ? `MT5 demo trade executed. Ticket #${ticket}.` : "MT5 demo trade executed.");
      return true;
    }
    if(status.status==="failed"){
      setMessage(`MT5 execution failed: ${status.result?.error ?? "unknown bridge error"}`);
      return false;
    }
    setMessage("Trade queued — waiting for MT5 bridge...");
    await new Promise(resolve=>setTimeout(resolve,1500));
  }
  setMessage("Trade is still queued. Check Alerts or Trades for the latest status.");
  return false;
}

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
  useEffect(()=>{
    let mounted=true;
    const load=async()=>{
      try{
        const data=await api.marketCandles(symbol,interval,80);
        if(mounted)setCandles(Array.isArray(data?.candles)?data.candles:[]);
      }catch{
        if(mounted)setCandles([]);
      }
    };
    load();
    const timer=setInterval(load,60000);
    return()=>{mounted=false;clearInterval(timer)};
  },[symbol,interval]);
  const closes=candles.map(c=>Number(c.close)).filter(Number.isFinite);
  const min=closes.length?Math.min(...closes):0;
  const max=closes.length?Math.max(...closes):0;
  const range=max-min||1;
  const points=closes.slice(-60);
  const height=180;
  const levelY=(value:number)=>range?Math.max(0,Math.min(height,(1-(value-min)/range)*height)):height/2;
  return <View style={s.chartWrap}>
    <View style={s.chartHeader}>
      <Text style={s.chartTitle}>PRICE CHART</Text>
      <View style={s.intervalRow}>
        {(["5m","15m","1h"] as const).map(v=><Pressable key={v} onPress={()=>setIntervalValue(v)} style={[s.intervalButton,interval===v&&s.intervalActive]}><Text style={[s.intervalText,interval===v&&s.intervalTextActive]}>{v.toUpperCase()}</Text></Pressable>)}
      </View>
    </View>
    {points.length<2
      ? <View style={s.chartEmpty}><ActivityIndicator color={colors.green}/><Text style={s.chartEmptyText}>Loading price data...</Text></View>
      : <View style={s.chart}>
          <View style={s.chartGrid}/>
          {entry>0&&<View style={[s.levelLine,{top:levelY(entry)}]}><Text style={s.levelText}>ENTRY {entry.toFixed(2)}</Text></View>}          {stopLoss>0&&<View style={[s.levelLine,s.slLine,{top:levelY(stopLoss)}]}><Text style={s.levelText}>SL {stopLoss.toFixed(2)}</Text></View>}          {takeProfit>0&&<View style={[s.levelLine,s.tpLine,{top:levelY(takeProfit)}]}><Text style={s.levelText}>TP {takeProfit.toFixed(2)}</Text></View>}
          {support>0&&<View style={[s.levelLine,s.supportLine,{top:levelY(support)}]}><Text style={s.levelText}>SUP {support.toFixed(2)}</Text></View>}          {resistance>0&&<View style={[s.levelLine,s.resistanceLine,{top:levelY(resistance)}]}><Text style={s.levelText}>RES {resistance.toFixed(2)}</Text></View>}
          {candles.slice(-60).map((c,index)=>{
            const open=Number(c.open), close=Number(c.close), high=Number(c.high), low=Number(c.low);
            const x=index/Math.max(candles.slice(-60).length,1)*100;
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
function reasonValue(reason:string,label:string,positive:string,negative:string){
  if(reason.includes(positive)) return positive;
  if(reason.includes(negative)) return negative;
  return negative;
}

export default function Markets(){
  const [rows,setRows]=useState<any[]|null>(null);
  const [message,setMessage]=useState("");

  useEffect(()=>{
    let mounted=true;
    const load=async()=>{
      try{
        const data=await api.markets();
        if(mounted)setRows(Array.isArray(data)?data:[]);
      }catch{
        if(mounted)setRows([]);
      }
    };
    load();
    // The backend keeps a short-lived scanner cache; polling every 15s
    // avoids hammering the API and keeps the phone responsive.
    const timer=setInterval(load,15000);
    return()=>{mounted=false;clearInterval(timer)};
  },[]);

  return <ScrollView style={s.screen} contentContainerStyle={s.c}>
    <Text style={s.title}>Markets</Text>
    <Text style={s.sub}>Live cloud market intelligence</Text>

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
              <Pressable style={s.approve} onPress={async()=>{
                setMessage(`Checking ${r.symbol}...`);
                try{
                  const result=await api.openTrade(r);
                  if(result.pending && result.command_id){
                    const ok=await waitForCommand(result.command_id,setMessage);
                    if(ok){ const refreshed=await api.markets(); setRows(Array.isArray(refreshed)?refreshed:[]); }
                  }else{
                    setMessage(`${r.symbol} trade approved and opened.`);
                    const refreshed=await api.markets(); setRows(Array.isArray(refreshed)?refreshed:[]);
                  }
                }catch(e){
                  setMessage(`Trade blocked: ${e instanceof Error?e.message:"risk check failed"}`);
                }
              }}>
                <Text style={s.approveText}>VALIDATE + APPROVE</Text>
              </Pressable>}
          </View>

          <View style={s.divider}/>          <PriceChart symbol={r.symbol} entry={Number(r.entry||0)} stopLoss={Number(r.stop_loss||0)} takeProfit={Number(r.take_profit||0)} support={Number(deep.timeframes?.["15m"]?.structure?.support||0)} resistance={Number(deep.timeframes?.["15m"]?.structure?.resistance||0)}/>

          <Text style={s.sectionTitle}>SIGNAL QUALITY</Text>
          <View style={s.qualityCard}>
            <QualityRow label="1H Direction" value={direction}/>
            <QualityRow label="15M Setup" value={setup}/>
            <QualityRow label="5M Direction" value={entryTf}/>
            <QualityRow label="Entry Trigger" value={trigger}/>
            <QualityRow label="Risk / Reward" value="1 : 2"/>
          </View>

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
  c:{padding:18,paddingTop:58,gap:12},
  title:{color:colors.text,fontSize:28,fontWeight:"900"},
  sub:{color:colors.muted,marginBottom:4},
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
  chartWrap:{marginBottom:14},
  chartHeader:{flexDirection:"row",justifyContent:"space-between",alignItems:"center",marginBottom:8},
  chartTitle:{color:colors.text,fontSize:10,fontWeight:"900",letterSpacing:1},
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