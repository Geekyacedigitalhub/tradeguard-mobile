import {ScrollView,StyleSheet,Text,View,Pressable,ActivityIndicator} from "react-native";
import {Ionicons} from "@expo/vector-icons";
import {useEffect,useMemo,useState} from "react";
import {Panel} from "../../src/components/Panel";
import {colors} from "../../src/theme";
import {api} from "../../src/api";

const tabs=["indicators","candles","signals","macro"];
const labels:any={indicators:"Indicators",candles:"Candles",signals:"Signals",macro:"Macro"};

export default function Knowledge(){
  const [data,setData]=useState<any>(null);
  const [tab,setTab]=useState("indicators");
  const [query,setQuery]=useState("");
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState("");

  useEffect(()=>{
    api.knowledgeLibrary().then(setData).catch((e:any)=>setError(e?.message??"Research library unavailable")).finally(()=>setLoading(false));
  },[]);

  const items=useMemo(()=>{
    const list=data?.[tab]??[];
    const q=query.trim().toLowerCase();
    return q?list.filter((x:any)=>JSON.stringify(x).toLowerCase().includes(q)):list;
  },[data,tab,query]);

  return <ScrollView style={s.screen} contentContainerStyle={s.c}>
    <View style={s.header}>
      <View style={{flex:1}}>
        <Text style={s.eyebrow}>TRADEGUARD RESEARCH ENGINE</Text>
        <Text style={s.title}>Trader Knowledge</Text>
        <Text style={s.sub}>Learn what the evidence means before you trade it.</Text>
      </View>
      <View style={s.icon}><Ionicons name="school-outline" size={24} color={colors.green}/></View>
    </View>

    <Panel>
      <Text style={s.mission}>{data?.mission??"Research-backed trading intelligence."}</Text>
      <Text style={s.note}>This library explains indicators, candle behavior, signals, risk and macro context. It does not promise profitable outcomes.</Text>
    </Panel>

    <View style={s.chips}>
      {tabs.map(x=><Pressable key={x} onPress={()=>setTab(x)} style={[s.chip,x===tab&&s.active]}><Text style={[s.chipText,x===tab&&s.activeText]}>{labels[x]}</Text></Pressable>)}
    </View>

    {loading?<Panel><View style={s.loading}><ActivityIndicator color={colors.green}/><Text style={s.sub}>Loading research library…</Text></View></Panel>:null}
    {error?<Panel><Text style={s.error}>{error}</Text></Panel>:null}

    {!loading&&data?.principles?.length?<Panel>
      <Text style={s.section}>CORE TRADING RULES</Text>
      {data.principles.slice(0,5).map((x:string,i:number)=><View key={i} style={s.rule}><Ionicons name="checkmark-circle-outline" size={16} color={colors.green}/><Text style={s.ruleText}>{x}</Text></View>)}
    </Panel>:null}

    {!loading&&items.map((item:any)=><Panel key={item.slug}>
      <View style={s.cardHead}>
        <View style={{flex:1}}><Text style={s.cardTitle}>{item.name}</Text><Text style={s.category}>{item.category??item.group??"Research"}</Text></View>
        <Ionicons name={tab==="indicators"?"analytics-outline":tab==="candles"?"candlestick-outline":tab==="signals"?"flash-outline":"globe-outline"} size={20} color={colors.green}/>
      </View>
      <Text style={s.label}>WHAT IT IS</Text><Text style={s.body}>{item.what??item.meaning??""}</Text>
      {item.read?<><Text style={s.label}>HOW TO READ IT</Text><Text style={s.body}>{item.read}</Text></>:null}
      {item.best?<><Text style={s.label}>BEST USE</Text><Text style={s.body}>{item.best}</Text></>:null}
      {item.confirmation?<><Text style={s.label}>CONFIRMATION</Text><Text style={s.body}>{item.confirmation}</Text></>:null}
      {item.warning?<><Text style={s.label}>WARNING</Text><Text style={s.warning}>{item.warning}</Text></>:null}
      {item.avoid?<><Text style={s.label}>WHEN TO AVOID</Text><Text style={s.warning}>{item.avoid}</Text></>:null}
      {item.source?<Text style={s.source}>Source: {item.source}</Text>:null}
    </Panel>)}

    {!loading&&data?.sources?.length?<Panel>
      <Text style={s.section}>RESEARCH SOURCES</Text>
      {data.sources.map((x:any)=><Text key={x.url} style={s.sourceLine}>{x.name}</Text>)}
    </Panel>:null}
  </ScrollView>
}

const s=StyleSheet.create({
  screen:{flex:1,backgroundColor:colors.background},c:{padding:18,paddingTop:58,paddingBottom:34,gap:14},
  header:{flexDirection:"row",alignItems:"center",gap:12},eyebrow:{color:colors.green,fontSize:9,fontWeight:"900",letterSpacing:1.1},title:{color:colors.text,fontSize:25,fontWeight:"900",marginTop:4},sub:{color:colors.muted,fontSize:11,marginTop:4},icon:{width:48,height:48,borderRadius:14,backgroundColor:"#09271b",borderWidth:1,borderColor:"#1b513a",alignItems:"center",justifyContent:"center"},
  mission:{color:colors.text,fontSize:13,fontWeight:"800",lineHeight:20},note:{color:colors.muted,fontSize:10,lineHeight:16,marginTop:9},
  chips:{flexDirection:"row",gap:8},chip:{borderWidth:1,borderColor:colors.border,borderRadius:20,paddingHorizontal:12,paddingVertical:8},active:{borderColor:colors.green,backgroundColor:"#09271b"},chipText:{color:colors.muted,fontSize:10,fontWeight:"800"},activeText:{color:colors.green},
  section:{color:colors.green,fontSize:10,fontWeight:"900",letterSpacing:1.1},rule:{flexDirection:"row",gap:8,marginTop:11},ruleText:{color:colors.text,fontSize:11,lineHeight:17,flex:1},
  cardHead:{flexDirection:"row",alignItems:"center",gap:10,marginBottom:12},cardTitle:{color:colors.text,fontSize:15,fontWeight:"900"},category:{color:colors.green,fontSize:9,fontWeight:"800",marginTop:3},label:{color:colors.muted,fontSize:8,fontWeight:"900",letterSpacing:1,marginTop:10},body:{color:colors.text,fontSize:11,lineHeight:17,marginTop:4},warning:{color:"#ffb5bf",fontSize:11,lineHeight:17,marginTop:4},source:{color:"#789184",fontSize:9,marginTop:12},sourceLine:{color:colors.muted,fontSize:10,lineHeight:17,marginTop:7},loading:{alignItems:"center",gap:8},error:{color:"#ffb5bf",fontSize:11}
});
