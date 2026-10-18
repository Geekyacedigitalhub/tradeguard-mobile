import {ScrollView,StyleSheet,Text,View,Pressable,ActivityIndicator} from "react-native";
import {Ionicons} from "@expo/vector-icons";
import {router} from "expo-router";
import {useEffect,useRef,useState} from "react";
import {AppState} from "react-native";
import {Panel} from "../../src/components/Panel";
import {colors,radii,shadows} from "../../src/theme";
import {api} from "../../src/api";
