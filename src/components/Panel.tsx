import {PropsWithChildren} from "react";
import {StyleSheet,View} from "react-native";
import {colors,radii,shadows} from "../theme";

export function Panel({children}:PropsWithChildren){
  return <View style={styles.panel}>{children}</View>
}

const styles=StyleSheet.create({
  panel:{
    backgroundColor:colors.surface,
    borderWidth:1,
    borderColor:colors.border,
    borderRadius:radii.lg,
    padding:16,
    ...shadows.card
  }
});
