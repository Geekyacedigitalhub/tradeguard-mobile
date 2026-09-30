import {PropsWithChildren} from "react";
import {StyleSheet,View} from "react-native";
import {colors} from "../theme";

export function Panel({children}:PropsWithChildren){
  return <View style={styles.panel}>{children}</View>
}

const styles=StyleSheet.create({
  panel:{
    backgroundColor:colors.surface,
    borderWidth:1,
    borderColor:colors.border,
    borderRadius:18,
    padding:16,
    shadowColor:"#000",
    shadowOpacity:0.18,
    shadowRadius:12,
    shadowOffset:{width:0,height:6},
    elevation:3
  }
});