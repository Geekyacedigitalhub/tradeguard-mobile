import {useEffect, useRef, useState} from "react";
import {Animated, Easing, Pressable, StyleSheet, Text, View} from "react-native";
import {colors,radii,shadows} from "../theme";

/** A ticking clock used for relative timestamps ("synced 12s ago"). */
export function useNow(intervalMs = 1000): number {
  const [now,setNow]=useState(()=>Date.now());
  useEffect(()=>{
    const timer=setInterval(()=>setNow(Date.now()),intervalMs);
    return()=>clearInterval(timer);
  },[intervalMs]);
  return now;
}

export function formatAge(ms: number | null): string {
  if(ms===null || !Number.isFinite(ms) || ms<0) return "—";
  const seconds=Math.floor(ms/1000);
  if(seconds<60) return `${seconds}s`;
  const minutes=Math.floor(seconds/60);
  if(minutes<60) return `${minutes}m ${seconds%60}s`;
  const hours=Math.floor(minutes/60);
  return `${hours}h ${minutes%60}m`;
}

/** Status LED with a soft breathing halo while the engine is live. */
export function Pulse({color=colors.green,size=9,active=true}:{color?:string;size?:number;active?:boolean}){
  const glow=useRef(new Animated.Value(0)).current;
  useEffect(()=>{
    if(!active){glow.setValue(0);return;}
    const loop=Animated.loop(Animated.sequence([
      Animated.timing(glow,{toValue:1,duration:1100,easing:Easing.inOut(Easing.ease),useNativeDriver:true}),
      Animated.timing(glow,{toValue:0,duration:1100,easing:Easing.inOut(Easing.ease),useNativeDriver:true}),
    ]));
    loop.start();
    return()=>loop.stop();
  },[active,glow]);
  return <View style={{width:size,height:size,alignItems:"center",justifyContent:"center"}}>
    {active?<Animated.View style={{
      position:"absolute",width:size*2.6,height:size*2.6,borderRadius:size*1.3,
      backgroundColor:color,opacity:glow.interpolate({inputRange:[0,1],outputRange:[0,0.06]}),
    }}/>:null}
    <View style={{width:size,height:size,borderRadius:size/2,backgroundColor:color}}/>
  </View>;
}

export function Chip({label,color=colors.muted,solid=false}:{label:string;color?:string;solid?:boolean}){
  return <View style={[styles.chip,{borderColor:color+(solid?"":"66"),backgroundColor:solid?color:"transparent"}]}>
    <Text style={[styles.chipText,{color:solid?colors.background:color}]}>{label}</Text>
  </View>;
}

export function SectionTitle({label,right}:{label:string;right?:string}){
  return <View style={styles.sectionRow}>
    <Text style={styles.sectionLabel}>{label}</Text>
    {right?<Text style={styles.sectionRight}>{right}</Text>:null}
    <View style={styles.sectionRule}/>
  </View>;
}

export type Tone="default"|"green"|"red"|"amber"|"blue";

export function toneColor(tone:Tone):string{
  if(tone==="green") return colors.green;
  if(tone==="red") return colors.red;
  if(tone==="amber") return colors.amber;
  if(tone==="blue") return colors.blue;
  return colors.text;
}

/** Dense metric tile used across the bot console. */
export function Stat({label,value,sub,tone="default",emphasis=false}:{label:string;value:string;sub?:string;tone?:Tone;emphasis?:boolean}){
  const color=toneColor(tone);
  return <View style={[styles.stat,emphasis&&styles.statEmphasis]}>
    <Text style={styles.statLabel}>{label}</Text>
    <Text style={[styles.statValue,emphasis&&styles.statValueLarge,{color}]} numberOfLines={1} adjustsFontSizeToFit>{value}</Text>
    {sub?<Text style={styles.statSub} numberOfLines={1}>{sub}</Text>:null}
  </View>;
}

/** Utilisation meter. `value` and `limit` share the caller's units. */
export function Gauge({label,value,limit,format,emptyLabel}:{
  label:string;
  value:number|null;
  limit:number|null;
  format:(value:number)=>string;
  emptyLabel?:string;
}){
  const usable=value!==null&&limit!==null&&Number.isFinite(value)&&Number.isFinite(limit)&&limit>0;
  const pct=usable?Math.max(0,Math.min(100,(Math.max(0,value!)/limit!)*100)):0;
  const color=pct>=90?colors.red:pct>=70?colors.amber:colors.green;
  return <View style={styles.gauge}>
    <View style={styles.gaugeHead}>
      <Text style={styles.gaugeLabel}>{label}</Text>
      <Text style={[styles.gaugeValue,{color:usable?color:colors.muted2}]}>
        {usable?`${format(Math.max(0,value!))} / ${format(limit!)}`:(emptyLabel??"—")}
      </Text>
    </View>
    <View style={styles.gaugeTrack}>
      <View style={[styles.gaugeFill,{width:`${usable?Math.max(pct,1.5):0}%`,backgroundColor:color}]}/>
    </View>
    <Text style={styles.gaugeFoot}>{usable?`${pct.toFixed(1)}% of limit`:"limit unavailable"}</Text>
  </View>;
}

export function Toggle({value,onChange,disabled,busy}:{value:boolean;onChange:()=>void;disabled?:boolean;busy?:boolean}){
  const position=useRef(new Animated.Value(value?1:0)).current;
  useEffect(()=>{
    Animated.timing(position,{toValue:value?1:0,duration:180,easing:Easing.out(Easing.cubic),useNativeDriver:true}).start();
  },[value,position]);
  return <Pressable
    accessibilityRole="switch"
    accessibilityState={{checked:value,disabled:!!disabled}}
    disabled={disabled||busy}
    onPress={onChange}
    style={[styles.toggle,value&&styles.toggleOn,(disabled||busy)&&{opacity:0.55}]}>
    <Animated.View style={[styles.knob,{transform:[{translateX:position.interpolate({inputRange:[0,1],outputRange:[0,20]})}]}]}/>
  </Pressable>;
}

export function Stepper({value,onChange,step,min,max,format,disabled}:{
  value:number;
  onChange:(next:number)=>void;
  step:number;
  min:number;
  max:number;
  format:(value:number)=>string;
  disabled?:boolean;
}){
  const clamp=(next:number)=>Math.min(max,Math.max(min,Number(next.toFixed(4))));
  return <View style={styles.stepper}>
    <Pressable disabled={disabled||value<=min} onPress={()=>onChange(clamp(value-step))} style={[styles.stepButton,(disabled||value<=min)&&{opacity:0.35}]}>
      <Text style={styles.stepSymbol}>−</Text>
    </Pressable>
    <Text style={styles.stepValue}>{format(value)}</Text>
    <Pressable disabled={disabled||value>=max} onPress={()=>onChange(clamp(value+step))} style={[styles.stepButton,(disabled||value>=max)&&{opacity:0.35}]}>
      <Text style={styles.stepSymbol}>+</Text>
    </Pressable>
  </View>;
}

export function Segmented<T extends string>({options,value,onChange,disabledKeys,busy}:{
  options:ReadonlyArray<{key:T;label:string;hint?:string}>;
  value:T|null;
  onChange:(key:T)=>void;
  disabledKeys?:ReadonlySet<T>;
  busy?:boolean;
}){
  return <View style={styles.segments}>
    {options.map(option=>{
      const selected=value===option.key;
      const locked=!!disabledKeys?.has(option.key);
      return <Pressable
        key={option.key}
        disabled={busy||locked}
        onPress={()=>onChange(option.key)}
        style={[styles.segment,selected&&styles.segmentActive,locked&&{opacity:0.45},busy&&{opacity:0.6}]}>
        <Text style={[styles.segmentLabel,selected&&{color:colors.greenBright}]}>{option.label}</Text>
        {option.hint?<Text style={[styles.segmentHint,selected&&{color:colors.green}]}>{option.hint}</Text>:null}
      </Pressable>;
    })}
  </View>;
}

export function FeedRow({title,body,meta,color=colors.muted,last=false}:{
  title:string;
  body:string;
  meta:string;
  color?:string;
  last?:boolean;
}){
  return <View style={[styles.feedRow,!last&&styles.feedRowBorder]}>
    <View style={[styles.feedRail,{backgroundColor:color}]}/>
    <View style={{flex:1}}>
      <View style={styles.feedHead}>
        <Text style={[styles.feedTitle,{color}]} numberOfLines={1}>{title}</Text>
        <Text style={styles.feedMeta}>{meta}</Text>
      </View>
      <Text style={styles.feedBody} numberOfLines={2}>{body}</Text>
    </View>
  </View>;
}

export function PanelCard({children,glow=false,style}:{children:React.ReactNode;glow?:boolean;style?:object}){
  return <View style={[styles.card,glow&&styles.cardGlow,style]}>{children}</View>;
}

const styles=StyleSheet.create({
  chip:{paddingHorizontal:8,paddingVertical:4,borderRadius:radii.pill,borderWidth:1},
  chipText:{fontSize:8,fontWeight:"900",letterSpacing:.7},

  sectionRow:{flexDirection:"row",alignItems:"center",gap:8,marginTop:4},
  sectionLabel:{color:colors.text,fontSize:12,fontWeight:"900",letterSpacing:1},
  sectionRight:{color:colors.muted2,fontSize:8,fontWeight:"800",letterSpacing:.6},
  sectionRule:{flex:1,height:1,backgroundColor:colors.border},

  stat:{backgroundColor:colors.surface2,borderRadius:radii.md,padding:11,borderWidth:1,borderColor:colors.border,flex:1,minWidth:0},
  statEmphasis:{backgroundColor:colors.surface3,borderColor:colors.borderStrong},
  statLabel:{color:colors.muted2,fontSize:7,fontWeight:"900",letterSpacing:.8},
  statValue:{fontSize:15,fontWeight:"900",marginTop:5,letterSpacing:.2},
  statValueLarge:{fontSize:19},
  statSub:{color:colors.muted,fontSize:8,marginTop:3,fontWeight:"700"},

  gauge:{marginTop:12},
  gaugeHead:{flexDirection:"row",justifyContent:"space-between",alignItems:"baseline"},
  gaugeLabel:{color:colors.muted,fontSize:9,fontWeight:"800",letterSpacing:.4},
  gaugeValue:{fontSize:10,fontWeight:"900"},
  gaugeTrack:{height:6,borderRadius:6,backgroundColor:colors.surface3,overflow:"hidden",marginTop:6},
  gaugeFill:{height:6,borderRadius:6},
  gaugeFoot:{color:colors.muted2,fontSize:8,marginTop:4,fontWeight:"700"},

  toggle:{width:48,height:28,borderRadius:16,backgroundColor:"#22323d",padding:3,justifyContent:"center"},
  toggleOn:{backgroundColor:colors.greenDeep},
  knob:{width:22,height:22,borderRadius:11,backgroundColor:"#8fa3b0"},

  stepper:{flexDirection:"row",alignItems:"center",gap:10},
  stepButton:{width:30,height:30,borderRadius:9,borderWidth:1,borderColor:colors.borderStrong,backgroundColor:colors.surface2,alignItems:"center",justifyContent:"center"},
  stepSymbol:{color:colors.green,fontSize:16,fontWeight:"900",lineHeight:18},
  stepValue:{color:colors.text,fontSize:14,fontWeight:"900",minWidth:64,textAlign:"center"},

  segments:{gap:8},
  segment:{borderRadius:10,borderWidth:1,borderColor:colors.border,backgroundColor:colors.surface2,paddingVertical:11,paddingHorizontal:12},
  segmentActive:{borderColor:colors.borderGlow,backgroundColor:"#0d271d"},
  segmentLabel:{color:colors.textSoft,fontSize:11,fontWeight:"900",letterSpacing:.5},
  segmentHint:{color:colors.muted2,fontSize:8,marginTop:3,fontWeight:"700"},

  feedRow:{flexDirection:"row",gap:10,paddingVertical:10},
  feedRowBorder:{borderBottomWidth:1,borderBottomColor:colors.border},
  feedRail:{width:2,borderRadius:2,marginTop:2},
  feedHead:{flexDirection:"row",justifyContent:"space-between",alignItems:"baseline",gap:8},
  feedTitle:{fontSize:9,fontWeight:"900",letterSpacing:.6,flex:1},
  feedMeta:{color:colors.muted2,fontSize:8,fontWeight:"700"},
  feedBody:{color:colors.textSoft,fontSize:11,lineHeight:15,marginTop:3},

  card:{backgroundColor:colors.surface,borderWidth:1,borderColor:colors.border,borderRadius:radii.lg,padding:16,...shadows.card},
  cardGlow:{borderColor:colors.borderGlow},
});
