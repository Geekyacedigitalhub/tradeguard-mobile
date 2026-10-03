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
        if(mounted)setRows(data);
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
                    if(ok) setRows(await api.markets());
                  }else{
                    setMessage(`${r.symbol} trade approved and opened.`);
                    setRows(await api.markets());
                  }
                }catch(e){
                  setMessage(`Trade blocked: ${e instanceof Error?e.message:"risk check failed"}`);
                }
              }}>
                <Text style={s.approveText}>APPROVE</Text>
              </Pressable>}
          </View>

          <View style={s.divider}/>

          <Text style={s.sectionTitle}>SIGNAL QUALITY</Text>
          <View style={s.qualityCard}>
            <QualityRow label="1H Direction" value={direction}/>
            <QualityRow label="15M Setup" value={setup}/>
            <QualityRow label="5M Direction" value={entryTf}/>
            <QualityRow label="Entry Trigger" value={trigger}/>
            <QualityRow label="Risk / Reward" value="1 : 2"/>
          </View>

          <Text style={s.liveTitle}>DEEP RESEARCH GATE</Text><Text style={[s.deepDecision,{color:deepDecision==="TRADE CANDIDATE"?colors.green:deepDecision==="WAIT"?"#f2c94c":colors.red}]}>{deepDecision} · {deep.confluence??0}/100</Text><Text style={s.intelWhy}>{(deep.reasons||[]).slice(0,3).join(" · ")}</Text><Text style={s.liveTitle}>MARKET INTELLIGENCE</Text><Text style={s.intel}>{intel.regime||"UNKNOWN"} · {intel.session||"UNKNOWN"} · Range {intel.price_position_pct??"—"}%</Text><Text style={s.intelWhy}>{(intel.why_not_trade||[]).slice(0,2).join(" · ")}</Text><Text style={s.liveTitle}>MULTI-TIMEFRAME DATA</Text>
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
  metricValue:{color:colors.text,fontSize:11,fontWeight:"900",marginTop:4}
});