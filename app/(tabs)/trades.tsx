import {ScrollView,StyleSheet,Text,View,Pressable,ActivityIndicator} from "react-native";
import {useEffect,useState} from "react";
import {Panel} from "../../src/components/Panel"; import {colors} from "../../src/theme"; import {api} from "../../src/api";

export default function Trades(){
  const [trades,setTrades]=useState<any[]|null>(null);
  const [broker,setBroker]=useState<any>(null);
  const [message,setMessage]=useState("");
  const [view,setView]=useState<"open"|"history">("open");
  const load=()=>api.trades().then((x:any)=>setTrades(x.trades??[])).catch(()=>setTrades([]));
  const loadBroker=()=>api.brokerSnapshot().then(setBroker).catch(()=>setBroker(null));

  useEffect(()=>{
    load(); loadBroker();
    const timer=setInterval(load,5000);
    const bt=setInterval(loadBroker,5000);
    return()=>{clearInterval(timer);clearInterval(bt)};
  },[]);

  if(!trades)return <View style={s.loading}><ActivityIndicator color={colors.green}/></View>;

  const brokerOpen=broker?.connected&&Array.isArray(broker?.positions);
  const open=brokerOpen
    ? broker.positions.map((p:any)=>({
        id:p.ticket,
        mt5Ticket:p.ticket,
        symbol:p.symbol,
        side:p.side,
        quantity:p.volume,
        entry:p.price_open,
        current_price:p.price_current,
        stop_loss:p.stop_loss,
        take_profit:p.take_profit,
        realized_pnl:p.profit ?? 0,
        status:"open"
      }))
    : trades.filter(t=>t.status==="open");

  const closed=trades.filter(t=>t.status==="closed");

  const fmt=(value:any)=>{
    const n=Number(value);
    return Number.isFinite(n) ? n.toFixed(5) : "—";
  };
  const fmtPnl=(value:any)=>{
    const n=Number(value);
    return Number.isFinite(n) ? `${n>=0?"+":""}${n.toFixed(2)}` : "—";
  };

  return <ScrollView style={s.screen} contentContainerStyle={s.c}>
    <Text style={s.title}>Trades</Text>
    <Text style={s.sub}>{brokerOpen?"MT5 LIVE SYNC":"TradeGuard Paper Trading"} · refresh every 5 seconds</Text>

    {message!==""&&<Panel><Text style={s.label}>{message}</Text></Panel>}

    <View style={s.tabs}>
      <Pressable style={[s.tab,view==="open"&&s.tabActive]} onPress={()=>setView("open")}>
        <Text style={[s.tabText,view==="open"&&s.tabTextActive]}>OPEN TRADES</Text>
      </Pressable>
      <Pressable style={[s.tab,view==="history"&&s.tabActive]} onPress={()=>setView("history")}>
        <Text style={[s.tabText,view==="history"&&s.tabTextActive]}>TRADING HISTORY</Text>
      </Pressable>
    </View>

    {view==="open" && <>
      {open.length===0&&<Panel><Text style={s.label}>No open trades.</Text></Panel>}

      {open.map((t:any)=><Panel key={t.id}>
      <View style={s.row}>
        <View style={{flex:1}}>
          <Text style={s.symbol}>{t.symbol} · {t.side}</Text>
          <Text style={s.sub}>Qty {fmt(t.quantity)} · Entry {fmt(t.entry)} · Current {fmt(t.current_price)}</Text>
        </View>
        <Text style={s.profit}>{fmtPnl(t.realized_pnl)}</Text>
      </View>
      <Text style={s.label}>SL {fmt(t.stop_loss)} · TP {fmt(t.take_profit)}</Text>

      {t.status==="open"&&<Text style={s.label}>
        {brokerOpen ? "Live MT5 position." : "Unrealized P/L updates from the cloud price monitor."}
      </Text>}

      <Pressable style={s.close} onPress={async()=>{
        try{
          if(brokerOpen && t.mt5Ticket){
            const result:any=await api.closeMt5Trade(t.mt5Ticket);
            setMessage(result?.queued ? `Close request sent for MT5 ticket ${t.mt5Ticket}.` : "Close request sent.");
          }else{
            await api.closeTrade(t.id);
            setMessage(`${t.symbol} closed.`);
          }
          load(); loadBroker();
        }catch(e:any){
          setMessage(e?.message ? "Unable to close trade." : "Unable to close trade.");
        }
      }}>
        <Text style={s.closeText}>CLOSE TRADE</Text>
      </Pressable>
    </Panel>)}

      {open.length>0&&<Text style={s.label}>Open positions are synced from MT5 when the bridge is connected.</Text>}
    </View>}

    {view==="history" && <View>
      <Text style={s.section}>Trading History</Text>
      {closed.length===0
        ? <Panel><Text style={s.label}>No closed trades yet.</Text></Panel>
        : closed.map(t=><Panel key={t.id}>
            <View style={s.historyRow}>
              <View style={{flex:1}}>
                <Text style={s.symbol}>{t.symbol} · {t.side}</Text>
                <Text style={s.sub}>{t.close_reason??"manual"} · {t.closed_at ? new Date(t.closed_at).toLocaleString() : "closed"}</Text>
              </View>
              <Text style={[s.profit,{color:Number(t.realized_pnl)>=0?colors.green:colors.red}]}>{fmtPnl(t.realized_pnl)}</Text>
            </View>
          </Panel>)}
    </View>}

    {view==="open"&&<Pressable style={s.closeAll} onPress={async()=>{
      try{
        await api.closeAll();
        setMessage("All open TradeGuard trades closed.");
        load(); loadBroker();
      }catch(e){setMessage("Unable to close all trades.")}
    }}>
      <Text style={s.closeText}>CLOSE ALL</Text>
    </Pressable>
  </ScrollView>
}

const s=StyleSheet.create({
  screen:{flex:1,backgroundColor:colors.background},
  loading:{flex:1,backgroundColor:colors.background,alignItems:"center",justifyContent:"center"},
  c:{padding:18,paddingTop:58,gap:14},
  title:{color:colors.text,fontSize:28,fontWeight:"900"},
  section:{color:colors.text,fontSize:16,fontWeight:"800"},
  tabs:{flexDirection:"row",backgroundColor:colors.panel,borderRadius:12,padding:4,gap:4},
  tab:{flex:1,paddingVertical:11,borderRadius:9,alignItems:"center"},
  tabActive:{backgroundColor:colors.green},
  tabText:{color:colors.muted,fontSize:10,fontWeight:"900"},
  tabTextActive:{color:colors.background},
  historyRow:{flexDirection:"row",alignItems:"center"},
  row:{flexDirection:"row",alignItems:"center"},
  symbol:{color:colors.text,fontWeight:"900",fontSize:15},
  sub:{color:colors.muted,fontSize:11,marginTop:5},
  profit:{color:colors.green,fontWeight:"900",fontSize:18},
  label:{color:colors.muted,fontSize:12,marginTop:6},
  close:{marginTop:12,borderRadius:10,padding:11,alignItems:"center",backgroundColor:"#7f2635"},
  closeAll:{height:52,borderRadius:14,backgroundColor:"#a51f34",alignItems:"center",justifyContent:"center"},
  closeText:{color:colors.white,fontWeight:"900",fontSize:11}
});
