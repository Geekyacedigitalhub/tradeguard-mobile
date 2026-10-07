import {ScrollView,StyleSheet,Text,View,Pressable,ActivityIndicator,TextInput} from "react-native";
import {useEffect,useState} from "react";
import {Panel} from "../../src/components/Panel";
import {colors} from "../../src/theme";
import {api} from "../../src/api";

export default function Trades(){
  const [trades,setTrades]=useState<any[]|null>(null);
  const [broker,setBroker]=useState<any>(null);
  const [message,setMessage]=useState("");
  const [view,setView]=useState<"open"|"history"|"journal">("open");
  const [journal,setJournal]=useState<any[]>([]);
  const [journalStats,setJournalStats]=useState<any>(null);
  const [journalSymbol,setJournalSymbol]=useState("");
  const [journalNotes,setJournalNotes]=useState("");
  const loadJournal=()=>api.journal().then((x:any)=>setJournal(x.entries??[])).catch(()=>setJournal([]));
  const loadJournalStats=()=>api.journalStats().then(setJournalStats).catch(()=>setJournalStats(null));

  const load=()=>api.trades().then((x:any)=>setTrades(x.trades??[])).catch(()=>setTrades([]));
  const loadBroker=()=>api.brokerSnapshot().then(setBroker).catch(()=>setBroker(null));

  useEffect(()=>{
    load();
    loadBroker();
    loadJournal();
    loadJournalStats();
    const timer=setInterval(load,30000);
    const bt=setInterval(loadBroker,30000);
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

  return (
    <ScrollView style={s.screen} contentContainerStyle={s.c}>
      <Text style={s.title}>Trades</Text>
      <Text style={s.sub}>{brokerOpen?"MT5 LIVE SYNC":"TradeGuard Paper Trading"} · refresh every 15 seconds</Text>

      {message!=="" ? <Panel><Text style={s.label}>{message}</Text></Panel> : null}

      <View style={s.tabs}>
        <Pressable style={[s.tab,view==="open"&&s.tabActive]} onPress={()=>setView("open")}>
          <Text style={[s.tabText,view==="open"&&s.tabTextActive]}>OPEN TRADES</Text>
        </Pressable>
        <Pressable style={[s.tab,view==="history"&&s.tabActive]} onPress={()=>setView("history")}>
          <Text style={[s.tabText,view==="history"&&s.tabTextActive]}>HISTORY</Text>
        </Pressable>
        <Pressable style={[s.tab,view==="journal"&&s.tabActive]} onPress={()=>{setView("journal");loadJournal();loadJournalStats()}}>
          <Text style={[s.tabText,view==="journal"&&s.tabTextActive]}>JOURNAL</Text>
        </Pressable>
      </View>

      {view==="journal" ? (
        <View>
          <Panel>
            <Text style={s.section}>TRADE JOURNAL</Text>
            <Text style={s.label}>SYMBOL</Text>
            <TextInput value={journalSymbol} onChangeText={setJournalSymbol} placeholder="EURUSD" placeholderTextColor={colors.muted} style={s.input}/><Text style={s.label}>NOTES</Text><TextInput value={journalNotes} onChangeText={setJournalNotes} placeholder="What did you see, why did you enter, what did you learn?" placeholderTextColor={colors.muted} multiline style={[s.input,s.notesInput]}/><Pressable style={s.save} onPress={async()=>{if(!journalSymbol.trim())return;await api.addJournal({symbol:journalSymbol.trim().toUpperCase(),notes:journalNotes});setJournalSymbol("");setJournalNotes("");loadJournal();loadJournalStats()}}><Text style={s.saveText}>SAVE JOURNAL ENTRY</Text></Pressable>
          </Panel>
          {journalStats?<Panel><View style={s.journalStats}><Text style={s.label}>ENTRIES {journalStats.entries}</Text><Text style={s.label}>WIN RATE {journalStats.win_rate}%</Text><Text style={s.label}>TOTAL R {journalStats.total_r}</Text></View></Panel>:null}
          {journal.map((j:any)=><Panel key={j.id}><View style={s.historyRow}><View style={{flex:1}}><Text style={s.symbol}>{j.symbol}{j.side?` · ${j.side}`:""}</Text><Text style={s.sub}>{j.created_at?new Date(j.created_at).toLocaleString():""}</Text><Text style={s.label}>{j.notes||"No notes"}</Text></View><Pressable onPress={async()=>{await api.deleteJournal(j.id);loadJournal();loadJournalStats()}}><Text style={s.delete}>DELETE</Text></Pressable></View></Panel>)}
        </View>
      ) : null}

      {view==="open" ? (
        <View>
          {open.length===0 ? <Panel><Text style={s.label}>No open trades.</Text></Panel> : null}

          {open.map((t:any)=>(
            <Panel key={t.id}>
              <View style={s.row}>
                <View style={{flex:1}}>
                  <Text style={s.symbol}>{t.symbol} · {t.side}</Text>
                  <Text style={s.sub}>Qty {fmt(t.quantity)} · Entry {fmt(t.entry)} · Current {fmt(t.current_price)}</Text>
                </View>
                <Text style={s.profit}>{fmtPnl(t.realized_pnl)}</Text>
              </View>

              <Text style={s.label}>SL {fmt(t.stop_loss)} · TP {fmt(t.take_profit)}</Text>

              {t.status==="open" ? (
                <Text style={s.label}>
                  {brokerOpen ? "Live MT5 position." : "Unrealized P/L updates from the cloud price monitor."}
                </Text>
              ) : null}

              <Pressable
                style={s.close}
                onPress={async()=>{
                  try{
                    if(brokerOpen && t.mt5Ticket){
                      const result:any=await api.closeMt5Trade(t.mt5Ticket);
                      setMessage(result?.queued ? `Close request sent for MT5 ticket ${t.mt5Ticket}.` : "Close request sent.");
                    }else{
                      await api.closeTrade(t.id);
                      setMessage(`${t.symbol} closed.`);
                    }
                    load();
                    loadBroker();
                  }catch(e:any){
                    setMessage("Unable to close trade.");
                  }
                }}
              >
                <Text style={s.closeText}>CLOSE TRADE</Text>
              </Pressable>
            </Panel>
          ))}

          {open.length>0 ? (
            <Text style={s.label}>Open positions are synced from the Cloud MT5 terminal.</Text>
          ) : null}
        </View>
      ) : null}

      {view==="history" ? (
        <View>
          <Text style={s.section}>Trading History</Text>
          {closed.length===0 ? (
            <Panel><Text style={s.label}>No closed trades yet.</Text></Panel>
          ) : (
            closed.map((t:any)=>(
              <Panel key={t.id}>
                <View style={s.historyRow}>
                  <View style={{flex:1}}>
                    <Text style={s.symbol}>{t.symbol} · {t.side}</Text>
                    <Text style={s.sub}>
                      {t.close_reason??"manual"} · {t.closed_at ? new Date(t.closed_at).toLocaleString() : "closed"}
                    </Text>
                  </View>
                  <Text style={[s.profit,{color:Number(t.realized_pnl)>=0?colors.green:colors.red}]}>
                    {fmtPnl(t.realized_pnl)}
                  </Text>
                </View>
              </Panel>
            ))
          )}
        </View>
      ) : null}

      {view==="open" ? (
        <Pressable
          style={s.closeAll}
          onPress={async()=>{
            try{
              const result:any=await api.closeAll();
              setMessage(result?.queued ? `Close-all request sent for ${result.count ?? 0} Cloud MT5 position${result.count === 1 ? "" : "s"}.` : "All open trades closed.");
              load();
              loadBroker();
            }catch(e){
              setMessage("Unable to close all trades.");
            }
          }}
        >
          <Text style={s.closeText}>CLOSE ALL</Text>
        </Pressable>
      ) : null}
    </ScrollView>
  );
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
  tabTextActive:{color:colors.background,fontSize:10,fontWeight:"900"},
  historyRow:{flexDirection:"row",alignItems:"center"},
  row:{flexDirection:"row",alignItems:"center"},
  symbol:{color:colors.text,fontWeight:"900",fontSize:15},
  sub:{color:colors.muted,fontSize:11,marginTop:5},
  profit:{color:colors.green,fontWeight:"900",fontSize:18},
  label:{color:colors.muted,fontSize:12,marginTop:6},
  close:{marginTop:12,borderRadius:10,padding:11,alignItems:"center",backgroundColor:"#7f2635"},
  closeAll:{height:52,borderRadius:14,backgroundColor:"#a51f34",alignItems:"center",justifyContent:"center"},
  closeText:{color:colors.white,fontWeight:"900",fontSize:11},
  input:{borderWidth:1,borderColor:colors.border,borderRadius:10,color:colors.text,padding:10,marginTop:7,marginBottom:10},notesInput:{minHeight:80,textAlignVertical:"top"},save:{backgroundColor:colors.green,borderRadius:10,padding:12,alignItems:"center"},saveText:{color:colors.background,fontWeight:"900",fontSize:10},journalStats:{flexDirection:"row",justifyContent:"space-between"},delete:{color:colors.red,fontSize:9,fontWeight:"900"},
});