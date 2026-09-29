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

export default function Markets(){
  const [rows,setRows]=useState<any[]|null>(null);
  const [message,setMessage]=useState("");
  useEffect(()=>{
    let mounted=true;
    const load=async()=>{try{const data=await api.markets();if(mounted)setRows(data)}catch{if(mounted)setRows([])}};
    load();
    const timer=setInterval(load,5000);
    return()=>{mounted=false;clearInterval(timer)};
  },[]);
  return <ScrollView style={s.screen} contentContainerStyle={s.c}>
    <Text style={s.title}>Markets</Text>
    <Text style={s.sub}>Live server signals</Text>
    {message!==""&&<Panel><Text style={s.message}>{message}</Text></Panel>}
    {rows===null?<ActivityIndicator color={colors.green}/>:rows.map(r=><Panel key={r.symbol}>
      <View style={s.row}>
        <View style={{flex:1}}><Text style={s.symbol}>{r.symbol}</Text><Text style={s.sub2}>{r.reason}</Text></View>
        <Text style={[s.score,{color:r.signal==="BUY"?colors.green:r.signal==="SELL"?colors.red:colors.muted}]}>{r.score}</Text>
        <Text style={s.sig}>{r.signal}</Text>
        {r.signal!=="NO TRADE"&&<Pressable style={s.approve} onPress={async()=>{
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
        }}><Text style={s.approveText}>APPROVE</Text></Pressable>}
      </View>
    </Panel>)}
  </ScrollView>
}

const s=StyleSheet.create({
  screen:{flex:1,backgroundColor:colors.background},
  c:{padding:18,paddingTop:58,gap:12},
  title:{color:colors.text,fontSize:28,fontWeight:"900"},
  sub:{color:colors.muted,marginBottom:4},
  row:{flexDirection:"row",alignItems:"center",gap:14},
  symbol:{color:colors.text,fontSize:16,fontWeight:"800"},
  sub2:{color:colors.muted,fontSize:11,marginTop:5},
  score:{fontSize:24,fontWeight:"900"},
  sig:{color:colors.text,fontSize:10,fontWeight:"900",width:70,textAlign:"right"},
  approve:{backgroundColor:colors.green,paddingHorizontal:10,paddingVertical:8,borderRadius:8},
  approveText:{color:colors.background,fontSize:10,fontWeight:"900"},
  message:{color:colors.text,fontSize:12,fontWeight:"700"}
});
