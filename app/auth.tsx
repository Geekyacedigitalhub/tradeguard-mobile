import { useState } from "react";
import { Alert, Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { router } from "expo-router";
import { api } from "../src/api";
import { colors } from "../src/theme";

export default function Auth() {
  const [mode,setMode]=useState<"login"|"register">("login");
  const [email,setEmail]=useState("");
  const [password,setPassword]=useState("");
  const [name,setName]=useState("");
  const [loading,setLoading]=useState(false);

  async function submit(){
    if(!email || password.length<8) return Alert.alert("Check your details","Use a valid email and a password of at least 8 characters.");
    setLoading(true);
    try {
      const result = mode==="login" ? await api.login({email,password}) : await api.register({email,password,display_name:name||undefined});
      await api.saveToken(result.token);
      router.replace("/(tabs)");
    } catch(e:any) {
      Alert.alert("TradeGuard", e?.message || "Authentication failed");
    } finally { setLoading(false); }
  }

  return <View style={s.screen}>
    <Text style={s.logo}>TRADEGUARD</Text>
    <Text style={s.title}>{mode==="login" ? "Welcome back" : "Create your account"}</Text>
    <Text style={s.sub}>Your trading dashboard, secured to your account.</Text>
    {mode==="register" && <TextInput value={name} onChangeText={setName} placeholder="Display name" placeholderTextColor={colors.muted} style={s.input}/>}
    <TextInput value={email} onChangeText={setEmail} autoCapitalize="none" keyboardType="email-address" placeholder="Email" placeholderTextColor={colors.muted} style={s.input}/>
    <TextInput value={password} onChangeText={setPassword} secureTextEntry placeholder="Password" placeholderTextColor={colors.muted} style={s.input}/>
    <Pressable disabled={loading} onPress={submit} style={s.button}><Text style={s.buttonText}>{loading ? "Please wait..." : mode==="login" ? "Sign in" : "Create account"}</Text></Pressable>
    <Pressable onPress={()=>setMode(mode==="login"?"register":"login")}><Text style={s.switch}>{mode==="login" ? "New to TradeGuard? Create an account" : "Already have an account? Sign in"}</Text></Pressable>
  </View>;
}
const s=StyleSheet.create({
  screen:{flex:1,backgroundColor:colors.background,padding:24,justifyContent:"center",gap:14},
  logo:{color:colors.green,fontSize:18,fontWeight:"900",letterSpacing:2},
  title:{color:colors.text,fontSize:30,fontWeight:"900",marginTop:10},
  sub:{color:colors.muted,fontSize:14,lineHeight:21,marginBottom:12},
  input:{backgroundColor:colors.panel,borderColor:colors.border,borderWidth:1,borderRadius:12,color:colors.text,padding:15,fontSize:15},
  button:{backgroundColor:colors.green,borderRadius:12,padding:16,alignItems:"center",marginTop:4},
  buttonText:{color:"#021008",fontWeight:"900",fontSize:15},
  switch:{color:colors.green,textAlign:"center",fontWeight:"700",marginTop:8}
});