import {Animated, Easing, StyleSheet, Text, View} from "react-native";
import {useEffect, useRef, useState} from "react";
import {colors} from "../theme";

export type TapeItem = {symbol: string; price: number; change: number};

const ITEM_WIDTH = 138;

export function TickerTape({items}: {items: TapeItem[]}) {
  const animRef = useRef<Animated.Value | null>(null);
  const [anim, setAnim] = useState<Animated.Value | null>(null);
  const count = items.length;

  useEffect(() => {
    if (count === 0) return;
    if (!animRef.current) animRef.current = new Animated.Value(0);
    const value = animRef.current;
    value.setValue(0);
    const loop = Animated.loop(
      Animated.timing(value, {
        toValue: -ITEM_WIDTH * count,
        duration: Math.max(24000, count * 3200),
        easing: Easing.linear,
        useNativeDriver: true
      })
    );
    loop.start();
    setAnim(value);
    return () => loop.stop();
  }, [count]);

  if (!anim || count === 0) return null;

  const row = (prefix: string) =>
    items.map((t, i) => (
      <View key={`${prefix}-${i}`} style={s.item}>
        <Text style={s.symbol}>{t.symbol}</Text>
        <Text style={s.price}>
          {t.price.toLocaleString(undefined, {
            minimumFractionDigits: t.price < 10 ? 4 : 2,
            maximumFractionDigits: t.price < 10 ? 5 : 2
          })}
        </Text>
        <Text style={[s.change, {color: t.change >= 0 ? colors.green : colors.red}]}>
          {t.change >= 0 ? "▲" : "▼"} {Math.abs(t.change).toFixed(2)}%
        </Text>
      </View>
    ));

  return (
    <View style={s.wrap}>
      <Animated.View style={{flexDirection: "row", transform: [{translateX: anim}]}}>
        {row("a")}
        {row("b")}
      </Animated.View>
    </View>
  );
}

const s = StyleSheet.create({
  wrap: {
    overflow: "hidden",
    height: 34,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.panel,
    flexDirection: "row",
    alignItems: "center"
  },
  item: {
    width: ITEM_WIDTH,
    height: 32,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 7,
    paddingRight: 4
  },
  symbol: {color: colors.muted, fontSize: 9, fontWeight: "900", letterSpacing: 0.5},
  price: {color: colors.text, fontSize: 10, fontWeight: "900"},
  change: {fontSize: 8, fontWeight: "900"}
});
