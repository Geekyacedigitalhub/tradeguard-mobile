import {ScrollView,StyleSheet,Text,View,Pressable,ActivityIndicator,TextInput,AppState} from "react-native";
import {useEffect,useRef,useState} from "react";
import {Panel} from "../../src/components/Panel";
import {colors,radii,shadows} from "../../src/theme";
import {api} from "../../src/api";
import {isCTraderSnapshotFresh} from "../../src/ctraderSnapshot";
import {onCTraderAccountChanged} from "../../src/ctraderAccountEvents";

export default function Trades(){
  const [trades,setTrades]=useState<any[]|null>(null);
  const [tradesError,setTradesError]=useState("");
  const [brokerSnapshot,setBrokerSnapshot]=useState<any>(null);
  const [brokerError,setBrokerError]=useState("");
  const [cloudConnection,setCloudConnection]=useState<any>(null);
  const cloudIdentityRef=useRef<{id:string;environment:string}|null>(null);
  const snapshotIdentityRef=useRef<{id:string;environment:string}|null>(null);
  const accountGeneration=useRef(0);
  const identityKey=(value:any)=>({id:value?.account_id==null?"":String(value.account_id).trim(),environment:String(value?.environment??"").trim().toLowerCase()});
  const [message,setMessage]=useState("");
  const [view,setView]=useState<"open"|"history"|"journal">("open");
  const [journal,setJournal]=useState<any[]>([]);
  const [journalStats,setJournalStats]=useState<any>(null);
  const [journalError,setJournalError]=useState("");
  const [journalStatsError,setJournalStatsError]=useState("");
  const [journalSymbol,setJournalSymbol]=useState("");
  const [journalNotes,setJournalNotes]=useState("");
  const loadJournal=()=>api.journal().then((x:any)=>{setJournal(Array.isArray(x?.entries)?x.entries:[]);setJournalError("");}).catch((e:any)=>setJournalError(e?.message??"Could not load journal entries."));
  const loadJournalStats=()=>api.journalStats().then((x:any)=>{setJournalStats(x);setJournalStatsError("");}).catch((e:any)=>setJournalStatsError(e?.message??"Journal statistics are temporarily unavailable."));

  const load=()=>api.trades().then((x:any)=>{setTrades(Array.isArray(x?.trades)?x.trades:[]);setTradesError("");}).catch((e:any)=>{setTradesError(e?.message??"Could not load paper trades. Check your connection and retry.");setTrades((current:any[]|null)=>current??[]);});
  const loadCloudConnection=()=>{
    const generation=accountGeneration.current;
    return api.ctraderConnection().then((x:any)=>{
    if(generation!==accountGeneration.current)return;
    const next=identityKey(x);
    const prior=cloudIdentityRef.current;
    const knownSnapshot=snapshotIdentityRef.current;
    const changed=!!prior&&(prior.id!==next.id||prior.environment!==next.environment);
    const conflict=!!knownSnapshot&&!!next.id&&(knownSnapshot.id!==next.id||knownSnapshot.environment!==next.environment);
    cloudIdentityRef.current=next;
    setCloudConnection(x);
    if(changed||conflict){snapshotIdentityRef.current=null;setBrokerSnapshot(null);setBrokerError("Selected cTrader account changed. Waiting for a fresh broker positions snapshot.");}
  }).catch((e:any)=>{
    if(generation!==accountGeneration.current)return;
    cloudIdentityRef.current=null;snapshotIdentityRef.current=null;
    setCloudConnection(null);setBrokerSnapshot(null);
    setBrokerError(e?.message??"cTrader connection status unavailable; broker positions are withheld.");
  });
  };
  const loadBrokerSnapshot=()=>{
    const generation=accountGeneration.current;
    return api.ctraderAccountSnapshot().then((x:any)=>{
    if(generation!==accountGeneration.current)return;
    const next=identityKey(x);
    const selected=cloudIdentityRef.current;
    if(!selected?.id||selected.id!==next.id||selected.environment!==next.environment){snapshotIdentityRef.current=null;setBrokerSnapshot(null);setBrokerError("Broker snapshot does not match the selected cTrader account. Previous positions are withheld.");return;}
    snapshotIdentityRef.current=next;setBrokerSnapshot(x);setBrokerError("");
  }).catch((e:any)=>{if(generation!==accountGeneration.current)return;snapshotIdentityRef.current=null;setBrokerSnapshot(null);setBrokerError(e?.message??"Broker snapshot unavailable; previous account positions are withheld until refreshed.");});
  };

  useEffect(()=>{
    let active=AppState.currentState==="active";
    let disposed=false;
    let loading=false;
    let refreshPending=false;
    let timer:ReturnType<typeof setInterval>|undefined;
    const refresh=()=>{
      if(!active||disposed)return;
      if(loading){refreshPending=true;return;}
      loading=true;
      refreshPending=false;
      void Promise.allSettled([
        Promise.allSettled([load(),loadJournal(),loadJournalStats()]),
        (async()=>{
          // Snapshot validation depends on the selected identity populated by the connection request.
          await loadCloudConnection();
          await loadBrokerSnapshot();
        })()
      ]).finally(()=>{
        loading=false;
        // Do not start a queued refresh after this screen has unmounted.
        if(refreshPending&&!disposed){refreshPending=false;refresh();}
      });
    };
    const unsubscribe=onCTraderAccountChanged(()=>{
      accountGeneration.current+=1;
      cloudIdentityRef.current=null;snapshotIdentityRef.current=null;
      setCloudConnection(null);setBrokerSnapshot(null);
      setBrokerError("cTrader account changed. Previous broker positions are withheld until the new account is verified.");
      refreshPending=true;
      refresh();
    });
    refresh();
    timer=setInterval(refresh,15000);
    const sub=AppState.addEventListener("change",state=>{
      active=state==="active";
      if(active)refresh();
    });
    return()=>{disposed=true;refreshPending=false;unsubscribe();if(timer)clearInterval(timer);sub.remove()};
  },[]);

  if(!trades)return <View style={s.loading}><ActivityIndicator color={colors.green}/></View>;

  const snapshotId=brokerSnapshot?.account_id==null?"":String(brokerSnapshot.account_id).trim();
  const cloudId=cloudConnection?.account_id==null?"":String(cloudConnection.account_id).trim();
  const snapshotEnvironment=String(brokerSnapshot?.environment??"").trim().toLowerCase();
  const cloudEnvironment=String(cloudConnection?.environment??"").trim().toLowerCase();
  const snapshotFresh=isCTraderSnapshotFresh(brokerSnapshot);
  const brokerSnapshotComplete=brokerSnapshot?.snapshot_status==="complete"&&brokerSnapshot?.positions_status!=="unavailable";
  const brokerIdentityVerified=!!snapshotId&&!!cloudId&&snapshotId===cloudId&&snapshotEnvironment==="demo"&&cloudEnvironment==="demo"&&!!cloudConnection?.connected&&!brokerError&&snapshotFresh&&brokerSnapshotComplete;
  const brokerOpen=!!brokerIdentityVerified;
  const brokerPositions=brokerIdentityVerified&&Array.isArray(brokerSnapshot?.positions)?brokerSnapshot.positions:[];
  const open=trades.filter(t=>t.status==="open");

  const closed=trades.filter(t=>t.status==="closed");

  const fmt=(value:any)=>{
    const n=Number(value);
    return Number.isFinite(n) ? n.toFixed(5) : "—";
  };

  // Never label realized P/L as open P/L. Only show a broker/paper unrealized field when the API explicitly provides it.
  const hasUnrealizedPnl=(trade:any)=>trade?.unrealized_pnl!==null&&trade?.unrealized_pnl!==undefined&&trade?.unrealized_pnl!==""&&Number.isFinite(Number(trade.unrealized_pnl));
  const totalOpenPnl=open.length===0?0:open.every(hasUnrealizedPnl)?open.reduce((sum:number,t:any)=>sum+Number(t.unrealized_pnl),0):null;

  const fmtPnl=(value:any)=>{
    if(value===null||value===undefined||value==="")return "—";
    const n=Number(value);
    return Number.isFinite(n) ? `${n>=0?"+":""}${n.toFixed(2)}` : "—";
  };

  return (
    <ScrollView style={s.screen} contentContainerStyle={s.c}>
      <View style={s.header}>
        <View><Text style={s.eyebrow}>TRADEGUARD / EXECUTION DESK</Text><Text style={s.title}>Positions</Text><Text style={s.sub}>Broker positions and local paper trades are shown separately.</Text></View>
        <View style={[s.connection,{borderColor:brokerOpen?(brokerError?colors.amber:colors.borderGlow):colors.border}]}><View style={[s.connectionDot,{backgroundColor:brokerOpen?(brokerError?colors.amber:colors.green):colors.red}]}/><Text style={[s.connectionText,{color:brokerOpen?(brokerError?colors.amber:colors.green):colors.red}]}>{brokerOpen?(brokerError?"BROKER DATA STALE":"BROKER SYNCED"):"BROKER SYNC UNAVAILABLE"}</Text></View>
      </View>
      <View style={s.terminalBar}>
        <View style={s.terminalStatus}><View style={s.terminalDot}/><Text style={s.terminalText}>CTRADER CLOUD</Text></View>
        <View style={s.terminalDivider}/>
        <Text style={s.terminalLock}>PAPER / READ-ONLY EXECUTION</Text>
      </View>

      <View style={s.exposureGrid}>
        <View style={s.exposure}><Text style={s.exposureLabel}>OPEN</Text><Text style={s.exposureValue}>{open.length}</Text></View>
        <View style={s.exposure}><Text style={s.exposureLabel}>OPEN P/L</Text><Text style={[s.exposureValue,{color:totalOpenPnl===null?colors.muted:totalOpenPnl>=0?colors.green:colors.red}]}>{fmtPnl(totalOpenPnl)}</Text></View>
        <View style={s.exposure}><Text style={s.exposureLabel}>MODE</Text><Text style={s.exposureValueSmall}>PAPER</Text></View>
      </View>

      {message!=="" ? <Panel><Text style={s.label}>{message}</Text></Panel> : null}
      {tradesError!=="" ? <Panel><Text style={s.label}>PAPER TRADES UNAVAILABLE · {tradesError}</Text><Pressable style={s.save} onPress={()=>{void load();}}><Text style={s.saveText}>RETRY PAPER TRADES</Text></Pressable></Panel> : null}

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
            <TextInput value={journalSymbol} onChangeText={setJournalSymbol} placeholder="EURUSD" placeholderTextColor={colors.muted} style={s.input}/><Text style={s.label}>NOTES</Text><TextInput value={journalNotes} onChangeText={setJournalNotes} placeholder="What did you see, why did you enter, what did you learn?" placeholderTextColor={colors.muted} multiline style={[s.input,s.notesInput]}/><Pressable disabled={!journalSymbol.trim()} style={[s.save,!journalSymbol.trim()&&{opacity:0.5}]} onPress={async()=>{const symbol=journalSymbol.trim().toUpperCase();if(!symbol)return;try{await api.addJournal({symbol,notes:journalNotes.trim()});setJournalSymbol("");setJournalNotes("");setMessage(`Journal entry saved for ${symbol}.`);void loadJournal();void loadJournalStats();}catch(e:any){setMessage(e?.message??"Could not save journal entry. Check your connection and try again.");}}}><Text style={s.saveText}>SAVE JOURNAL ENTRY</Text></Pressable>
          </Panel>
          {journalError!=="" ? <Panel><Text style={s.label}>JOURNAL ENTRIES UNAVAILABLE · {journalError}</Text><Pressable style={s.save} onPress={()=>{void loadJournal();}}><Text style={s.saveText}>RETRY JOURNAL</Text></Pressable></Panel> : null}
          {journalStatsError!=="" ? <Panel><Text style={s.label}>JOURNAL STATS UNAVAILABLE · {journalStatsError}</Text><Pressable style={s.save} onPress={()=>{void loadJournalStats();}}><Text style={s.saveText}>RETRY STATS</Text></Pressable></Panel> : null}
          {journalStats?<Panel><View style={s.journalStats}><Text style={s.label}>ENTRIES {journalStats.entries}</Text><Text style={s.label}>WIN RATE {journalStats.win_rate}%</Text><Text style={s.label}>TOTAL R {journalStats.total_r}</Text></View></Panel>:null}
          {journal.map((j:any)=><Panel key={j.id}><View style={s.historyRow}><View style={{flex:1}}><Text style={s.symbol}>{j.symbol}{j.side?` · ${j.side}`:""}</Text><Text style={s.sub}>{j.created_at?new Date(j.created_at).toLocaleString():""}</Text><Text style={s.label}>{j.notes||"No notes"}</Text></View><Pressable onPress={async()=>{try{await api.deleteJournal(j.id);setMessage(`Journal entry for ${j.symbol} deleted.`);void loadJournal();void loadJournalStats();}catch(e:any){setMessage(e?.message??"Could not delete journal entry. Check your connection and try again.");}}}><Text style={s.delete}>DELETE</Text></Pressable></View></Panel>)}
        </View>
      ) : null}

      {view==="open" ? (
        <View>
          <Panel>
            <Text style={s.section}>cTRADER CLOUD POSITIONS</Text>
            <Text style={s.sub}>{brokerIdentityVerified?`Verified demo account ${snapshotId} · ${brokerSnapshot.as_of?new Date(brokerSnapshot.as_of).toLocaleString():"timestamp unavailable"}`:!cloudConnection?"cTrader connection unavailable. Broker positions are withheld.":snapshotId&&cloudId&&snapshotId!==cloudId?"Account ID conflict. Broker positions are withheld.":"No current verified demo snapshot available."}</Text>
            {brokerError!==""?<Text style={s.label}>Refresh issue · {brokerError} Existing snapshot data is retained and may be stale.</Text>:null}{brokerSnapshot&&!snapshotFresh?<Text style={s.label}>Snapshot is stale or has no valid server timestamp (maximum age 60 seconds). Broker positions are withheld until a fresh snapshot arrives.</Text>:null}{brokerSnapshot&&snapshotFresh&&!brokerSnapshotComplete?<Text style={s.label}>Broker snapshot is partial or positions are unavailable. Broker positions remain hidden until a complete positions snapshot arrives.</Text>:null}
            {brokerIdentityVerified&&brokerPositions.length===0?<Text style={s.label}>The verified demo broker reports no open positions.</Text>:null}
            {brokerPositions.map((p:any)=>(
              <View key={String(p.position_id)} style={[s.brokerPosition,s.rowBorder]}>
                <View style={{flex:1}}>
                  <Text style={s.symbol}>Position #{p.position_id||"—"} · {p.side==="BUY"?"BUY":p.side==="SELL"?"SELL":"SIDE UNKNOWN"}</Text>
                  <Text style={s.sub}>{p.symbol??`Symbol ID ${p.symbol_id??"—"}`} · Broker volume {p.volume??"—"}</Text>
                  <Text style={s.sub}>Entry {p.entry_price??"—"}</Text>
                </View>
                <View style={s.brokerTag}><Text style={s.brokerTagText}>BROKER</Text></View>
              </View>
            ))}
            <Text style={s.label}>Broker positions are read-only here. Closing broker trades is disabled until position and volume handling are fully validated.</Text>
          </Panel>
          {open.length===0 ? <Panel><Text style={s.label}>No open paper trades.</Text></Panel> : null}

          {open.map((t:any)=>(
            <Panel key={t.id}>
              <View style={s.positionHead}>
                <View style={s.sideBadge}><Text style={[s.sideText,{color:t.side==="BUY"?colors.green:colors.red}]}>{t.side}</Text></View>
                <View style={{flex:1}}>
                  <Text style={s.symbol}>{t.symbol}</Text>
                  <Text style={s.sub}>Qty {fmt(t.quantity)} · Entry {fmt(t.entry)} · Current {fmt(t.current_price)}</Text>
                </View>
                <Text style={[s.profit,{color:hasUnrealizedPnl(t)?Number(t.unrealized_pnl)>=0?colors.green:colors.red:colors.muted}]}>{fmtPnl(t.unrealized_pnl)}</Text>
              </View>

              <View style={s.levels}>
                <View><Text style={s.levelLabel}>ENTRY</Text><Text style={s.levelValue}>{fmt(t.entry)}</Text></View>
                <View><Text style={s.levelLabel}>CURRENT</Text><Text style={s.levelValue}>{fmt(t.current_price)}</Text></View>
                <View><Text style={s.levelLabel}>SL</Text><Text style={s.levelValue}>{fmt(t.stop_loss)}</Text></View>
                <View><Text style={s.levelLabel}>TP</Text><Text style={s.levelValue}>{fmt(t.take_profit)}</Text></View>
              </View>

              {t.status==="open" ? (
                <Text style={s.label}>
                  "Local paper position. Broker positions are displayed separately above."
                </Text>
              ) : null}

              <Pressable
                style={s.close}
                onPress={async()=>{
                  try{
                    await api.closeTrade(t.id);
                    setMessage(`${t.symbol} paper position closed.`);
                    load();
                  }catch(e:any){
                    setMessage("Unable to close paper position.");
                  }
                }}
              >
                <Text style={s.closeText}>CLOSE PAPER POSITION</Text>
              </Pressable>
            </Panel>
          ))}

          {open.length>0 ? (
            <Text style={s.label}>Local paper trades and read-only cTrader broker positions are separate lists. Broker positions above come from the last successful cloud snapshot.</Text>
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
          disabled={open.length===0}
          onPress={async()=>{
            const results=await Promise.allSettled(open.map((trade:any)=>api.closeTrade(trade.id)));
            const closed=results.filter((result:any)=>result.status==="fulfilled").length;
            const failed=results.length-closed;
            if(failed===0){
              setMessage(`Closed ${closed} paper position${closed===1?"":"s"}.`);
            }else{
              setMessage(`Closed ${closed} of ${results.length} paper positions. ${failed} failed; review the open positions and retry if needed.`);
            }
            void load();
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
  c:{padding:18,paddingTop:58,paddingBottom:112,gap:14},
  header:{flexDirection:"row",justifyContent:"space-between",alignItems:"flex-start",gap:10},
  terminalBar:{flexDirection:"row",alignItems:"center",gap:9,paddingHorizontal:12,paddingVertical:10,borderRadius:11,backgroundColor:colors.surface2,borderWidth:1,borderColor:colors.border},
  terminalStatus:{flexDirection:"row",alignItems:"center",gap:6},terminalDot:{width:6,height:6,borderRadius:6,backgroundColor:colors.green},terminalText:{color:colors.green,fontSize:8,fontWeight:"900",letterSpacing:.8},terminalDivider:{width:1,height:15,backgroundColor:colors.border},terminalLock:{color:colors.muted,fontSize:7,fontWeight:"900",letterSpacing:.6,flexShrink:1},
  eyebrow:{color:colors.green,fontSize:8,fontWeight:"900",letterSpacing:1.5},
  title:{color:colors.text,fontSize:28,fontWeight:"900",marginTop:3},
  connection:{flexDirection:"row",alignItems:"center",gap:5,paddingHorizontal:9,paddingVertical:7,borderRadius:radii.pill,borderWidth:1,backgroundColor:colors.surface2},
  connectionDot:{width:6,height:6,borderRadius:6},connectionText:{fontSize:7,fontWeight:"900",letterSpacing:.8},
  exposureGrid:{flexDirection:"row",gap:8},
  exposure:{flex:1,backgroundColor:colors.surface2,borderRadius:radii.md,borderWidth:1,borderColor:colors.border,padding:12,...shadows.card},
  exposureLabel:{color:colors.muted,fontSize:7,fontWeight:"900",letterSpacing:1},
  exposureValue:{color:colors.text,fontSize:19,fontWeight:"900",marginTop:5},
  exposureValueSmall:{color:colors.text,fontSize:12,fontWeight:"900",marginTop:8},
  section:{color:colors.text,fontSize:16,fontWeight:"800"},
  tabs:{flexDirection:"row",backgroundColor:colors.panel,borderRadius:12,padding:4,gap:4},
  tab:{flex:1,paddingVertical:11,borderRadius:9,alignItems:"center"},
  tabActive:{backgroundColor:colors.green},
  tabText:{color:colors.muted,fontSize:10,fontWeight:"900"},
  tabTextActive:{color:colors.background,fontSize:10,fontWeight:"900"},
  historyRow:{flexDirection:"row",alignItems:"center"},
  row:{flexDirection:"row",alignItems:"center"},
  positionHead:{flexDirection:"row",alignItems:"center",gap:10},
  brokerPosition:{flexDirection:"row",alignItems:"center",gap:10,paddingVertical:12},
  brokerTag:{borderWidth:1,borderColor:colors.borderGlow,borderRadius:7,paddingHorizontal:7,paddingVertical:5},
  brokerTagText:{color:colors.green,fontSize:7,fontWeight:"900",letterSpacing:.7},
  sideBadge:{paddingHorizontal:8,paddingVertical:5,borderRadius:7,backgroundColor:colors.surface3},
  sideText:{fontSize:8,fontWeight:"900"},
  levels:{flexDirection:"row",justifyContent:"space-between",alignItems:"center",marginTop:14,paddingTop:12,borderTopWidth:1,borderTopColor:colors.border},
  levelLabel:{color:colors.muted,fontSize:7,fontWeight:"900",letterSpacing:.7},
  levelValue:{color:colors.text,fontSize:10,fontWeight:"800",marginTop:4},
  symbol:{color:colors.text,fontWeight:"900",fontSize:15},
  sub:{color:colors.muted,fontSize:11,marginTop:5},
  profit:{color:colors.green,fontWeight:"900",fontSize:18},
  label:{color:colors.muted,fontSize:12,marginTop:6},
  close:{marginTop:12,borderRadius:10,padding:11,alignItems:"center",backgroundColor:"#7f2635"},
  closeAll:{height:52,borderRadius:14,backgroundColor:"#a51f34",alignItems:"center",justifyContent:"center"},
  closeText:{color:colors.white,fontWeight:"900",fontSize:11},
  input:{borderWidth:1,borderColor:colors.border,borderRadius:10,color:colors.text,padding:10,marginTop:7,marginBottom:10},notesInput:{minHeight:80,textAlignVertical:"top"},save:{backgroundColor:colors.green,borderRadius:10,padding:12,alignItems:"center"},saveText:{color:colors.background,fontWeight:"900",fontSize:10},journalStats:{flexDirection:"row",justifyContent:"space-between"},delete:{color:colors.red,fontSize:9,fontWeight:"900"},
});