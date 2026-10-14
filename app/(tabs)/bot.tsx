import {ScrollView,StyleSheet,Text,View,Pressable,ActivityIndicator} from "react-native";
import {useEffect,useState} from "react";
import {colors,radii,shadows} from "../../src/theme";
import {Panel} from "../../src/components/Panel";
import {api} from "../../src/api";

export default function Bot(){
 const [b,setB]=useState<any>(null);

 const load=async()=>{
  try{setB(await api.bot())}catch{}
 };

 useEffect(()=>{load()},[]);

 const action=(fn:()=>Promise<any>)=>fn().then(setB);

 if(!b)return <View style={s.loading}><ActivityIndicator color={colors.green}/></View>;

 return <ScrollView style={s.screen} contentContainerStyle={s.c}>
  <View style={s.header}><View style={{flex:1}}><Text style={s.eyebrow}>TRADEGUARD / AUTOMATION DESK</Text><Text style={s.title}>Autopilot</Text><Text style={s.sub}>Controlled automation with hard risk boundaries.</Text></View><View style={[s.statusChip,{borderColor:b.running?colors.borderGlow:colors.border}]}><View style={[s.statusDot,{backgroundColor:b.running?colors.green:colors.red}]}/><Text style={[s.statusText,{color:b.running?colors.green:colors.red}]}>{b.running?"ENGINE LIVE":"ENGINE IDLE"}</Text></View></View>

  <Panel>
   <View style={s.engineHead}><View><Text style={s.label}>ENGINE STATE</Text><Text style={s.state}>{b.running?"RUNNING":"STOPPED"}</Text></View><View style={s.guard}><Text style={s.guardText}>RISK GUARD</Text><Text style={s.guardState}>ACTIVE</Text></View></View>
   <Text style={s.muted}>Automation remains subject to strategy validation, risk approval and broker connectivity.</Text>
  </Panel>

  <Text style={s.section}>Execution Safety</Text>
  <Panel>
   <Text style={s.aiTitle}>cTRADER AUTO-EXECUTION LOCKED</Text>
   <Text style={s.muted}>Signal scanning and risk analysis can continue, but broker orders are blocked until account verification, broker-volume sizing, fresh quotes and mandatory stop-loss/take-profit protection pass end-to-end tests.</Text>
  </Panel>

  <Text style={s.section}>Execution Mode</Text>
  <Panel>{["signals_only","semi_auto"].map(m=><Pressable key={m} onPress={()=>api.updateMode(m).then(setB)} style={[s.mode,b.mode===m?s.active:null]}><Text style={s.modeText}>{m==="signals_only"?"SIGNALS ONLY":m==="semi_auto"?"SEMI-AUTO · SIGNAL ONLY":"SIGNALS ONLY"}</Text></Pressable>)}</Panel>

  <Text style={s.section}>Risk Command</Text>
  <Panel>
   <View style={s.riskBanner}><Text style={s.label}>PROTECTION PROFILE</Text><Text style={s.protected}>HARD RISK LIMITS ACTIVE</Text></View>
   <View style={s.line}><Text style={s.muted}>Risk / trade</Text><Text style={s.value}>{b.risk_per_trade??0.5}%</Text></View>
   <View style={s.line}><Text style={s.muted}>Daily loss limit</Text><Text style={s.value}>{b.daily_loss_limit??2}%</Text></View>
   <View style={s.line}><Text style={s.muted}>Max open trades</Text><Text style={s.value}>{b.max_open_trades??3}</Text></View>
   <View style={s.line}><Text style={s.muted}>Max drawdown</Text><Text style={s.value}>{b.max_drawdown??5}%</Text></View>
  </Panel>

  <Pressable style={s.stop} onPress={()=>action(b.running?api.stopBot:api.startBot)}><Text style={s.button}>{b.running?"STOP BOT":"START BOT"}</Text></Pressable>
  <Pressable style={s.emergency} onPress={()=>action(api.emergencyStop)}><Text style={s.emergencyText}>EMERGENCY STOP</Text></Pressable>
 </ScrollView>
}

const s=StyleSheet.create({
 screen:{flex:1,backgroundColor:colors.background},
 loading:{flex:1,backgroundColor:colors.background,alignItems:"center",justifyContent:"center"},
 c:{padding:18,paddingTop:58,paddingBottom:112,gap:14},
 header:{flexDirection:"row",justifyContent:"space-between",alignItems:"flex-start",gap:10},
 eyebrow:{color:colors.green,fontSize:8,fontWeight:"900",letterSpacing:1.5},
 title:{color:colors.text,fontSize:28,fontWeight:"900",marginTop:3},
 sub:{color:colors.muted,fontSize:10,lineHeight:15,marginTop:4},
 statusChip:{flexDirection:"row",alignItems:"center",gap:5,paddingHorizontal:9,paddingVertical:7,borderRadius:radii.pill,borderWidth:1,backgroundColor:colors.surface2},
 statusDot:{width:6,height:6,borderRadius:6},statusText:{fontSize:7,fontWeight:"900",letterSpacing:.8},
 label:{color:colors.muted,fontSize:8,fontWeight:"900",letterSpacing:1.1},
 engineHead:{flexDirection:"row",justifyContent:"space-between",alignItems:"center"},
 guard:{alignItems:"flex-end"},guardText:{color:colors.muted,fontSize:7,fontWeight:"900",letterSpacing:1},guardState:{color:colors.green,fontSize:10,fontWeight:"900",marginTop:3},
 riskBanner:{backgroundColor:colors.surface2,borderRadius:10,padding:10,marginBottom:7,borderWidth:1,borderColor:colors.border},
 protected:{color:colors.green,fontSize:9,fontWeight:"900",marginTop:4},

 state:{color:colors.green,fontSize:18,fontWeight:"900"},
 muted:{color:colors.muted,fontSize:12,marginTop:5},
 section:{color:colors.text,fontSize:16,fontWeight:"800"},
 aiHeader:{flexDirection:"row",alignItems:"center",gap:12},
 aiTitle:{color:colors.text,fontSize:14,fontWeight:"900"},
 toggle:{width:50,height:30,borderRadius:20,backgroundColor:"#24352d",padding:3,justifyContent:"center"},
 toggleOn:{backgroundColor:colors.green},
 knob:{width:24,height:24,borderRadius:12,backgroundColor:"#9aa8a2"},
 knobOn:{alignSelf:"flex-end",backgroundColor:colors.background},
 warning:{color:"#f6c76b",fontSize:11,lineHeight:16,marginTop:12},
 mode:{padding:13,borderRadius:12,borderWidth:1,borderColor:colors.border,marginBottom:9},
 active:{borderColor:colors.green,backgroundColor:"#0d271d"},
 modeText:{color:colors.text,fontWeight:"800"},
 line:{flexDirection:"row",justifyContent:"space-between",paddingVertical:10},
 value:{color:colors.text,fontWeight:"900"},
 stop:{height:56,borderRadius:16,backgroundColor:colors.green,alignItems:"center",justifyContent:"center"},
 button:{color:colors.background,fontWeight:"900"},
 emergency:{height:56,borderRadius:16,backgroundColor:"#a51f34",alignItems:"center",justifyContent:"center"},
 emergencyText:{color:colors.white,fontWeight:"900",fontSize:14}
});