import {Alert,AppState,ScrollView,StyleSheet,Text,View,Pressable,ActivityIndicator,TextInput} from "react-native";
import {useEffect,useRef,useState} from "react";
import {Panel} from "../../src/components/Panel";
import {colors,radii,shadows} from "../../src/theme";
import {api} from "../../src/api";

export default function Trades(){
  const [trades,setTrades]=useState<any[]|null>(null);
  const [ctrader,setCtrader]=useState<any>(null);
  const [brokerAccount,setBrokerAccount]=useState<any>(null);
  const [message,setMessage]=useState("");
  const [closingPositionId,setClosingPositionId]=useState<number|null>(null);
  const [closingAll,setClosingAll]=useState(false);
  const [tradesError,setTradesError]=useState("");
  const [ctraderError,setCtraderError]=useState("");
  const [brokerError,setBrokerError]=useState("");
  const [view,setView]=useState<"open"|"history"|"journal">("open");
  const [journal,setJournal]=useState<any[]>([]);
  const [journalStats,setJournalStats]=useState<any>(null);
  const [journalSymbol,setJournalSymbol]=useState("");
  const [journalNotes,setJournalNotes]=useState("");
  const screenMounted=useRef(false);
  const tradesRefreshInFlight=useRef(false);
  const statusRefreshInFlight=useRef(false);
  const brokerRefreshInFlight=useRef(false);
  const tradesRefreshQueued=useRef(false);
  const statusRefreshQueued=useRef(false);
  const brokerRefreshQueued=useRef(false);
  const loadJournal=()=>api.journal().then((x:any)=>setJournal(x.entries??[])).catch(()=>setJournal([]));
  const loadJournalStats=()=>api.journalStats().then(setJournalStats).catch(()=>setJournalStats(null));

  const load=(queueIfBusy=false)=>{
    if(tradesRefreshInFlight.current){if(queueIfBusy)tradesRefreshQueued.current=true;return Promise.resolve();}
    tradesRefreshInFlight.current=true;
    return api.trades().then((x:any)=>{if(screenMounted.current){setTrades(x.trades??[]);setTradesError("")}}).catch(()=>{if(screenMounted.current){setTradesError("TradeGuard records could not refresh. Showing the last successful snapshot.");setTrades(current=>current??[])}}).finally(()=>{tradesRefreshInFlight.current=false;if(screenMounted.current&&tradesRefreshQueued.current){tradesRefreshQueued.current=false;void load()}});
  };
  const loadCTrader=(queueIfBusy=false)=>{
    if(statusRefreshInFlight.current){if(queueIfBusy)statusRefreshQueued.current=true;return Promise.resolve();}
    statusRefreshInFlight.current=true;
    return api.ctraderStatus().then((x:any)=>{if(screenMounted.current){setCtrader(x);setCtraderError("")}}).catch(()=>{if(screenMounted.current)setCtraderError("cTrader status refresh failed. The last successful status is retained.")}).finally(()=>{statusRefreshInFlight.current=false;if(screenMounted.current&&statusRefreshQueued.current){statusRefreshQueued.current=false;void loadCTrader()}});
  };
  const loadBrokerAccount=(queueIfBusy=false)=>{
    if(brokerRefreshInFlight.current){if(queueIfBusy)brokerRefreshQueued.current=true;return Promise.resolve();}
    brokerRefreshInFlight.current=true;
    return api.ctraderAccount().then((x:any)=>{if(screenMounted.current){setBrokerAccount(x);setBrokerError("")}}).catch(()=>{if(screenMounted.current){setBrokerAccount(null);setBrokerError("Broker positions could not refresh. Account values and close controls are hidden until a fresh snapshot succeeds.")}}).finally(()=>{brokerRefreshInFlight.current=false;if(screenMounted.current&&brokerRefreshQueued.current){brokerRefreshQueued.current=false;void loadBrokerAccount()}});
  };

  useEffect(()=>{
    screenMounted.current=true;
    load();
    loadCTrader();
    loadBrokerAccount();
    loadJournal();
    loadJournalStats();
    const timer=setInterval(load,30000);
    const ct=setInterval(()=>{loadCTrader();loadBrokerAccount()},15000);
    const appStateSubscription=AppState.addEventListener("change",state=>{
      if(state==="active"){
        load(true);
        loadCTrader(true);
        loadBrokerAccount(true);
      }
    });
    return()=>{
      screenMounted.current=false;
      tradesRefreshQueued.current=false;
      statusRefreshQueued.current=false;
      brokerRefreshQueued.current=false;
      clearInterval(timer);
      clearInterval(ct);
      appStateSubscription.remove();
    };
  },[]);

  if(!trades)return <View style={s.loading}><ActivityIndicator color={colors.green}/></View>;

  const ctraderConnected=!!ctrader?.account_id;
  const ctraderEnvironment=String(ctrader?.environment||"").toLowerCase();
  const ctraderMode=ctraderEnvironment==="live"?"LIVE":ctraderEnvironment==="demo"?"DEMO":"NOT CONNECTED";
  const open=trades.filter(t=>t.status==="open");

  const closed=trades.filter(t=>t.status==="closed");

  const fmt=(value:any)=>{
    if(value===null||value===undefined||value==="")return "—";
    const n=Number(value);
    return Number.isFinite(n) ? n.toFixed(5) : "—";
  };

  const brokerUnrealizedPnl=brokerAccount?.connected && brokerAccountMatchesSelection && brokerAccount?.unrealized_pnl!==null && brokerAccount?.unrealized_pnl!==undefined && brokerAccount?.unrealized_pnl!=="" && Number.isFinite(Number(brokerAccount.unrealized_pnl)) ? Number(brokerAccount.unrealized_pnl) : null;
  const brokerCurrency=String(brokerAccount?.currency||"").trim();
  const brokerAccountMatchesSelection=!!ctrader?.account_id && Number.isSafeInteger(Number(ctrader.account_id)) && Number(ctrader.account_id)>0 && Number(brokerAccount?.account_id)===Number(ctrader.account_id) && String(brokerAccount?.environment||"").toLowerCase()===String(ctrader?.environment||"").toLowerCase();
  const brokerSyncedAt=brokerAccount?.updated_at ? new Date(brokerAccount.updated_at) : null;
  const brokerSnapshotTime=brokerSyncedAt && Number.isFinite(brokerSyncedAt.getTime()) ? brokerSyncedAt.toLocaleTimeString() : null;
  const brokerSnapshotAgeMs=brokerSyncedAt?Date.now()-brokerSyncedAt.getTime():null;
  const brokerSnapshotStale=brokerSnapshotAgeMs===null || !Number.isFinite(brokerSnapshotAgeMs) || brokerSnapshotAgeMs<0 || brokerSnapshotAgeMs>45000;
  const brokerControlsLocked=brokerSnapshotStale || brokerError!=="" || !brokerAccountMatchesSelection;
  const brokerPositions=brokerAccountMatchesSelection && Array.isArray(brokerAccount?.positions)?brokerAccount.positions:[];
  const brokerOpenCount=brokerAccount?.connected && brokerAccountMatchesSelection && !brokerSnapshotStale && brokerError==="" ? brokerPositions.length : null;
  const brokerReportedPositionCount=brokerAccount?.connected&&brokerAccountMatchesSelection&&!brokerSnapshotStale&&brokerError===""?(brokerAccount.positions_count!==null&&brokerAccount.positions_count!==undefined&&brokerAccount.positions_count!==""&&Number.isFinite(Number(brokerAccount.positions_count))&&Number(brokerAccount.positions_count)>=0?Math.floor(Number(brokerAccount.positions_count)):Array.isArray(brokerAccount.positions)?brokerAccount.positions.length:null):null;

  const fmtPnl=(value:any)=>{
    if(value===null||value===undefined||value==="")return "—";
    const n=Number(value);
    return Number.isFinite(n) ? `${n>=0?"+":""}${n.toFixed(2)}` : "—";
  };
  return (
    <ScrollView style={s.screen} contentContainerStyle={s.c}>
      <View style={s.header}>
        <View><Text style={s.eyebrow}>TRADEGUARD / EXECUTION DESK</Text><Text style={s.title}>Positions</Text><Text style={s.sub}>{ctraderConnected?"cTrader "+ctraderMode+" account selected":"No cTrader account selected"} · broker exposure monitor</Text></View>
        <View style={[s.connection,{borderColor:ctraderConnected?colors.borderGlow:colors.border}]}><View style={[s.connectionDot,{backgroundColor:ctraderConnected?colors.green:colors.red}]}/><Text style={[s.connectionText,{color:ctraderConnected?colors.green:colors.red}]}>{ctraderConnected?"cTRADER "+ctraderMode:"OFFLINE"}</Text></View>
      </View>

      {tradesError!=="" ? <Panel><Text style={s.warning}>{tradesError}</Text></Panel> : null}
      {ctraderError!=="" ? <Panel><Text style={s.warning}>{ctraderError}</Text></Panel> : null}
      {brokerError!=="" ? <Panel><Text style={s.warning}>{brokerError}</Text></Panel> : null}

      <View style={s.exposureGrid}>
        <View style={s.exposure}><Text style={s.exposureLabel}>BROKER OPEN</Text><Text style={s.exposureValue}>{brokerOpenCount===null?"—":brokerOpenCount}</Text></View>
        <View style={s.exposure}><Text style={s.exposureLabel}>BROKER U. P/L</Text><Text style={[s.exposureValue,{color:brokerUnrealizedPnl!==null?(brokerUnrealizedPnl>=0?colors.green:colors.red):colors.muted}]}>{brokerUnrealizedPnl===null?"—":`${fmtPnl(brokerUnrealizedPnl)}${brokerCurrency?` ${brokerCurrency}`:""}`}</Text></View>
        <View style={s.exposure}><Text style={s.exposureLabel}>MODE</Text><Text style={s.exposureValueSmall}>{ctraderConnected?ctraderMode:"NOT CONNECTED"}</Text></View>
      </View>

      {message!=="" ? <Panel><Text style={s.label}>{message}</Text></Panel> : null}

      {view==="open" ? (
        <Panel>
          <Text style={s.section}>BROKER-CONFIRMED cTRADER POSITIONS</Text>
          <Text style={s.label}>
            {brokerAccount?.connected
              ? `${brokerAccount.environment==="live"?"LIVE":"DEMO"} account · ${brokerReportedPositionCount===null?"position count unavailable":brokerReportedPositionCount+" position(s) confirmed in the latest fresh cTrader snapshot"}`
              : "Select and authorize a cTrader account to view broker positions."}
          </Text>
          <Text style={[s.label,brokerControlsLocked&&{color:colors.amber}]}>{brokerAccount?.connected ? `Broker snapshot · ${!brokerAccountMatchesSelection?"ACCOUNT MISMATCH":brokerSnapshotStale?"STALE":"FRESH"}${brokerSnapshotTime?` · last sync ${brokerSnapshotTime}`:" · sync time unavailable"}${brokerError!==""?" · REFRESH FAILED":""}` : "Broker snapshot unavailable; broker P/L is not displayed."}</Text>
          <Pressable
            accessibilityRole="button"
            disabled={closingAll||closingPositionId!==null}
            style={[s.refreshBroker,(closingAll||closingPositionId!==null)&&{opacity:0.5}]}
            onPress={async()=>{
              setMessage("Refreshing cTrader account, positions, and connection status…");
              await Promise.all([loadCTrader(),loadBrokerAccount()]);
              setMessage("Refresh finished. Check the snapshot timestamp and warnings before using any close control.");
            }}
          >
            <Text style={s.refreshBrokerText}>REFRESH BROKER SNAPSHOT</Text>
          </Pressable>
          {brokerAccount?.connected && brokerAccountMatchesSelection && !brokerSnapshotStale && brokerError==="" && (brokerAccount.positions??[]).length===0
            ? <Text style={s.label}>cTrader reports no open broker positions.</Text>
            : brokerAccount?.connected && (!brokerAccountMatchesSelection || brokerSnapshotStale || brokerError!=="") && (brokerAccount.positions??[]).length===0
              ? <Text style={[s.label,{color:colors.amber}]}>No positions are shown in the last snapshot, but it is stale or refresh failed. This does not confirm the account is flat.</Text>
              : null}
          {brokerAccount?.connected&&(brokerAccount.positions??[]).length>0 ? (
            <Pressable
              disabled={closingAll||closingPositionId!==null||brokerControlsLocked}
              style={[s.closeAll,(closingAll||closingPositionId!==null||brokerControlsLocked)&&{opacity:0.5}]}
              onPress={()=>{
                Alert.alert(
                  "Close all "+(brokerAccount.environment==="live"?"LIVE":"Demo")+" positions?",
                  "TradeGuard will submit a manual close request for every position in the selected cTrader "+(brokerAccount.environment==="live"?"LIVE":"Demo")+" account. This is an immediate market action and may realize losses or incur slippage. A queued request is not proof that a position has closed. Verify each result in cTrader.",
                  [
                    {text:"Cancel",style:"cancel"},
                    {text:"CLOSE ALL "+(brokerAccount.environment==="live"?"LIVE":"DEMO")+" POSITIONS",style:"destructive",onPress:async()=>{
                      if(closingAll||closingPositionId!==null)return;
                      setClosingAll(true);
                      try{
                        const result:any=await api.closeAll();
                        const rawIds=Array.isArray(result?.command_ids)?result.command_ids:[result?.command_id];
                        const commandIds=rawIds.map((id:any)=>Number(id)).filter((id:number)=>Number.isInteger(id)&&id>0);
                        if(commandIds.length===0){
                          setMessage(result?.position_count===0||result?.status==="no_open_positions"
                            ?"cTrader confirmed there were no open positions."
                            :result?.message||"Close All returned no valid command IDs; no close is confirmed. Check cTrader directly before retrying.");
                          await loadBrokerAccount();
                          return;
                        }
                        setMessage(`Close-all request queued for ${commandIds.length} cTrader position command(s). Checking each broker result…`);
                        const outcomes=await Promise.all(commandIds.map(async(commandId:number)=>{
                          let status:any=null;
                          for(let attempt=0;attempt<8;attempt++){
                            try{status=await api.cTraderCommand(commandId);}catch{status=null;}
                            if(status&&(status.status==="completed"||status.status==="failed"))break;
                            await new Promise(resolve=>setTimeout(resolve,1500));
                          }
                          return status;
                        }));
                        const unfinished=outcomes.filter((status:any)=>!status||(status.status!=="completed"&&status.status!=="failed")).length;
                         const perCommand:any[][]=outcomes.map((status:any)=>Array.isArray(status?.result?.positions)?status.result.positions:status?.result&&typeof status.result==="object"&&Object.keys(status.result).length>0?[status.result]:[]);
                         const positions:Array<any>=perCommand.flat();
                         const closed=positions.filter(item=>item?.status==="confirmed_closed").length;
                         const reduced=positions.filter(item=>item?.status==="confirmed_reduced").length;
                         const unexpected=positions.filter(item=>item?.status==="changed_unexpectedly").length;
                         const failedPositions=positions.filter(item=>item?.status==="failed").length;
                         const workerFailed=outcomes.filter((status:any,i:number)=>status?.status==="failed"&&(!perCommand[i].length||!perCommand[i].some(item=>item?.status==="failed"))).length;
                         const missingCompleted=outcomes.filter((status:any,i:number)=>status?.status==="completed"&&perCommand[i].length===0).length;
                         const failed=failedPositions+workerFailed;
                         const unconfirmed=Math.max(0,unfinished+missingCompleted+positions.filter(item=>!["confirmed_closed","confirmed_reduced","changed_unexpectedly","failed"].includes(item?.status)).length);
                         setMessage(`Close All result: ${closed} fully closed, ${reduced} partially reduced, ${failed} failed/worker-error, ${unexpected} unexpected broker-state change(s), ${unconfirmed} unconfirmed. Verify remaining positions in cTrader before retrying.`);
                        await Promise.all([loadCTrader(),loadBrokerAccount()]);
                      }catch(e:any){
                        setMessage(`Close All may have reached the cloud even though no result was received. Check cTrader and refresh positions before retrying. Details: ${String(e?.message||"request result unavailable")}`);
                        await Promise.all([loadCTrader(),loadBrokerAccount()]).catch(()=>{});
                      }finally{
                        setClosingAll(false);
                      }
                    }}
                  ]
                );
              }}>
              <Text style={s.closeAllText}>{closingAll?"SUBMITTING / VERIFYING CLOSES…":brokerControlsLocked?"REFRESH / VERIFY ACCOUNT":"CLOSE ALL "+(brokerAccount.environment==="live"?"LIVE":"DEMO")+" POSITIONS"}</Text>
            </Pressable>
          ):null}
          {brokerAccount?.environment==="live" && brokerPositions.length>0 ? <Text style={s.warning}>LIVE ACCOUNT: manual close controls only. Automated Live entries and automatic position amendments remain disabled. Check every close result in cTrader.</Text> : null}
          {brokerPositions.map((p:any)=>(
            <View key={String(p.position_id)} style={s.brokerPosition}>
              <View style={s.positionHead}>
                <View style={s.sideBadge}><Text style={[s.sideText,{color:p.side==="BUY"?colors.green:colors.red}]}>{p.side}</Text></View>
                <View style={{flex:1}}>
                  <Text style={s.symbol}>{p.symbol}</Text>
                  <Text style={s.sub}>Broker position #{p.position_id} · protocol volume {p.volume_protocol_units}</Text>
                </View>
              </View>
              <View style={s.levels}>
                <View><Text style={s.levelLabel}>ENTRY</Text><Text style={s.levelValue}>{fmt(p.entry_price)}</Text></View>
                <View><Text style={s.levelLabel}>SL</Text><Text style={s.levelValue}>{fmt(p.stop_loss)}</Text></View>
                <View><Text style={s.levelLabel}>TP</Text><Text style={s.levelValue}>{fmt(p.take_profit)}</Text></View>
              </View>
              <View style={s.levels}>
                <View><Text style={s.levelLabel}>UNREALIZED P/L</Text><Text style={[s.levelValue,{color:p.unrealized_pnl==null?colors.muted:Number(p.unrealized_pnl)>=0?colors.green:colors.red}]}>{p.unrealized_pnl==null?"—":`${Number(p.unrealized_pnl)>=0?"+":""}${Number(p.unrealized_pnl).toFixed(2)}${brokerCurrency? ` ${brokerCurrency}`:""}`}</Text></View>
              </View>
              {brokerAccount?.environment==="demo"||brokerAccount?.environment==="live" ? (
                <Pressable disabled={closingPositionId!==null||brokerControlsLocked} style={[s.close,(closingPositionId!==null||brokerControlsLocked)&&{opacity:0.55}]} onPress={()=>{
                  const performClose=async()=>{
                  if(closingPositionId!==null)return;
                  setClosingPositionId(p.position_id);
                  try{
                    const result:any=await api.closeCTraderPosition(p.position_id,p.volume_protocol_units);
                    if(!Number.isInteger(Number(result?.command_id))||Number(result?.command_id)<=0){
                      setMessage(`Close request for position #${p.position_id} returned no valid command ID. No close is confirmed; check cTrader directly before retrying.`);
                      await Promise.all([loadCTrader(),loadBrokerAccount()]);
                      return;
                    }
                    setMessage(`Close request queued for cTrader position #${p.position_id}. Checking broker result…`);
                    let finalStatus:any=null;
                    for(let attempt=0;attempt<8;attempt++){
                      await new Promise(resolve=>setTimeout(resolve,1500));
                      try{
                        finalStatus=await api.cTraderCommand(result.command_id);
                        if(finalStatus?.status==="completed"||finalStatus?.status==="failed") break;
                      }catch{}
                    }
                    const outcome=finalStatus?.result;
                    const outcomeStatus=outcome?.status;
                    if(finalStatus?.status==="failed" || (finalStatus?.status==="completed" && outcomeStatus==="failed")){
                      setMessage(`Close command failed for position #${p.position_id}: ${outcome?.error || outcome?.message || outcome?.reason || "the worker reported an error"}. Broker state is not proven by this status; check cTrader before retrying.`);
                    }else if(finalStatus?.status==="completed" && outcomeStatus==="confirmed_closed"){
                      setMessage(`Broker confirmed cTrader position #${p.position_id} closed.`);
                    }else if(finalStatus?.status==="completed" && outcomeStatus==="confirmed_reduced"){
                      setMessage(`Broker confirmed a partial close for cTrader position #${p.position_id}. Remaining volume: ${outcome?.volume_after ?? "unknown"}.`);
                    }else if(finalStatus?.status==="completed" && outcomeStatus==="changed_unexpectedly"){
                      setMessage(`Position #${p.position_id} changed unexpectedly. Check cTrader directly before taking further action.`);
                    }else if(finalStatus?.status==="completed" && outcomeStatus==="submitted_unconfirmed"){
                      setMessage(`Close request for position #${p.position_id} was submitted, but broker confirmation failed. Check cTrader before retrying.`);
                    }else{
                      setMessage(`Close request for position #${p.position_id} is still unconfirmed. Check cTrader before retrying.`);
                    }
                    await Promise.all([loadCTrader(),loadBrokerAccount()]);
                  }catch(e:any){setMessage(`Close request for cTrader position #${p.position_id} may have reached the cloud even though no result was received. Check cTrader and refresh the position before retrying. Details: ${String(e?.message||"request result unavailable")}`); await Promise.all([loadCTrader(),loadBrokerAccount()]).catch(()=>{});}
                  finally{setClosingPositionId(null);}
                  };
                  if(brokerAccount?.environment==="live"){
                    Alert.alert(
                      "Close LIVE cTrader position?",
                      "This sends a real market close request for this position and may realize a loss or incur slippage. Confirm the position and verify the result in cTrader.",
                      [
                        {text:"Cancel",style:"cancel"},
                        {text:"CLOSE LIVE POSITION",style:"destructive",onPress:()=>{void performClose();}}
                      ]
                    );
                  }else{
                    void performClose();
                  }
                }}>
                  <Text style={s.closeText}>{closingPositionId===p.position_id?"CHECKING BROKER…":brokerSnapshotStale||brokerError!==""?"REFRESH REQUIRED":"CLOSE "+(brokerAccount?.environment==="live"?"LIVE":"DEMO")+" cTRADER POSITION"}</Text>
                </Pressable>
              ) : (
                <Text style={s.label}>Position controls are unavailable until a valid cTrader account is selected.</Text>
              )}
              {(brokerAccount?.environment==="demo"||brokerAccount?.environment==="live")&&brokerControlsLocked ? <Text style={s.warning}>{!brokerAccountMatchesSelection?"Close controls are locked because the broker snapshot does not match the currently selected cTrader account. Refresh both status and broker data before retrying.":"Close controls are locked until a fresh broker snapshot is available. Refresh the account data and verify the position in cTrader before retrying."}</Text> : null}
            </View>
          ))}
          <Text style={s.label}>Broker positions above come directly from cTrader. TradeGuard's internal trade records below are shown separately.</Text>
        </Panel>
      ) : null}

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
          {open.length===0 ? <Panel><Text style={s.label}>{tradesError ? "Open trades could not be confirmed because TradeGuard could not refresh." : "No open trades."}</Text></Panel> : null}

          {open.map((t:any)=>(
            <Panel key={t.id}>
              <View style={s.positionHead}>
                <View style={s.sideBadge}><Text style={[s.sideText,{color:t.side==="BUY"?colors.green:colors.red}]}>{t.side}</Text></View>
                <View style={{flex:1}}>
                  <Text style={s.symbol}>{t.symbol}</Text>
                  <Text style={s.sub}>Qty {fmt(t.quantity)} · Entry {fmt(t.entry)} · Current {fmt(t.current_price)}</Text>
                </View>
                <Text style={[s.profit,{color:Number(t.realized_pnl)>=0?colors.green:colors.red}]}>{fmtPnl(t.realized_pnl)}</Text>
              </View>

              <View style={s.levels}>
                <View><Text style={s.levelLabel}>ENTRY</Text><Text style={s.levelValue}>{fmt(t.entry)}</Text></View>
                <View><Text style={s.levelLabel}>CURRENT</Text><Text style={s.levelValue}>{fmt(t.current_price)}</Text></View>
                <View><Text style={s.levelLabel}>SL</Text><Text style={s.levelValue}>{fmt(t.stop_loss)}</Text></View>
                <View><Text style={s.levelLabel}>TP</Text><Text style={s.levelValue}>{fmt(t.take_profit)}</Text></View>
              </View>

              {t.status==="open" ? (
                <Text style={s.label}>
                  {ctraderConnected ? `cTrader ${ctraderMode} account selected. Broker positions are not yet synced into this list.` : "No cTrader account selected. These are TradeGuard records, not broker-confirmed positions."}
                </Text>
              ) : null}

              <Text style={s.label}>Internal TradeGuard record only. This control cannot close a broker position; use the broker-confirmed cTrader position above.</Text>
            </Panel>
          ))}

          {open.length>0 ? (
            <Text style={s.label}>Open trades are listed from TradeGuard. Live cTrader position sync is being finalized.</Text>
          ) : null}
        </View>
      ) : null}

      {view==="history" ? (
        <View>
          <Text style={s.section}>Trading History</Text>
          {closed.length===0 ? (
            <Panel><Text style={s.label}>{tradesError ? "Trade history could not be confirmed because TradeGuard could not refresh." : "No closed trades yet."}</Text></Panel>
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

    </ScrollView>
  );
}

const s=StyleSheet.create({
  screen:{flex:1,backgroundColor:colors.background},
  loading:{flex:1,backgroundColor:colors.background,alignItems:"center",justifyContent:"center"},
  c:{padding:18,paddingTop:58,paddingBottom:112,gap:14},
  header:{flexDirection:"row",justifyContent:"space-between",alignItems:"flex-start",gap:10},
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
  brokerPosition:{marginTop:12,paddingTop:12,borderTopWidth:1,borderTopColor:colors.border},
  row:{flexDirection:"row",alignItems:"center"},
  positionHead:{flexDirection:"row",alignItems:"center",gap:10},
  sideBadge:{paddingHorizontal:8,paddingVertical:5,borderRadius:7,backgroundColor:colors.surface3},
  sideText:{fontSize:8,fontWeight:"900"},
  levels:{flexDirection:"row",justifyContent:"space-between",alignItems:"center",marginTop:14,paddingTop:12,borderTopWidth:1,borderTopColor:colors.border},
  levelLabel:{color:colors.muted,fontSize:7,fontWeight:"900",letterSpacing:.7},
  levelValue:{color:colors.text,fontSize:10,fontWeight:"800",marginTop:4},
  symbol:{color:colors.text,fontWeight:"900",fontSize:15},
  sub:{color:colors.muted,fontSize:11,marginTop:5},
  profit:{color:colors.green,fontWeight:"900",fontSize:18},
  label:{color:colors.muted,fontSize:12,marginTop:6},
  warning:{color:"#f59e0b",fontSize:11,marginTop:6},
  close:{marginTop:12,borderRadius:10,padding:11,alignItems:"center",backgroundColor:"#7f2635"},
  closeText:{color:colors.white,fontWeight:"900",fontSize:11},
  refreshBroker:{marginTop:10,borderRadius:9,padding:11,alignItems:"center",borderWidth:1,borderColor:colors.border,backgroundColor:colors.surface2},
  refreshBrokerText:{color:colors.green,fontWeight:"900",fontSize:10,letterSpacing:0.6},
  closeAll:{marginTop:14,borderRadius:10,padding:14,alignItems:"center",backgroundColor:"#a51f34",borderWidth:1,borderColor:"#f87171"},
  closeAllText:{color:colors.white,fontWeight:"900",fontSize:11},
  input:{borderWidth:1,borderColor:colors.border,borderRadius:10,color:colors.text,padding:10,marginTop:7,marginBottom:10},notesInput:{minHeight:80,textAlignVertical:"top"},save:{backgroundColor:colors.green,borderRadius:10,padding:12,alignItems:"center"},saveText:{color:colors.background,fontWeight:"900",fontSize:10},journalStats:{flexDirection:"row",justifyContent:"space-between"},delete:{color:colors.red,fontSize:9,fontWeight:"900"},
});