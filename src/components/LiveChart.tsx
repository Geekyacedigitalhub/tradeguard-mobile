import {StyleSheet, Text, View} from "react-native";
import {Svg, Path, Line, Defs, LinearGradient, Stop} from "react-native-svg";
import {colors} from "../theme";

type Props = {
  values: number[];
  up: boolean;
  height?: number;
  gradientId: string;
};

const W = 340;
const PAD = 6;

function fmtPrice(v: number): string {
  return v.toLocaleString(undefined, {
    minimumFractionDigits: v < 10 ? 4 : 2,
    maximumFractionDigits: v < 10 ? 5 : 2
  });
}

export function LiveChart({values, up, height = 132, gradientId}: Props) {
  if (values.length < 2) {
    return (
      <View style={[s.placeholder, {height}]}>
        <Text style={s.placeholderInner}>BUILDING LIVE CHART…</Text>
      </View>
    );
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || Math.abs(max) * 0.001 || 1;
  const pts = values.map((v, i) => {
    const x = PAD + (i / (values.length - 1)) * (W - 2 * PAD);
    const y = PAD + (1 - (v - min) / span) * (height - 2 * PAD);
    return [x, y] as const;
  });
  const line = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(" ");
  const area = `${line} L${(W - PAD).toFixed(1)} ${(height - PAD).toFixed(1)} L${PAD} ${(height - PAD).toFixed(1)} Z`;
  const last = pts[pts.length - 1];
  const color = up ? colors.green : colors.red;
  const lastTop = Math.max(2, Math.min(height - 10, (last[1] / height) * height - 4));

  return (
    <View style={{height}}>
      <Svg width="100%" height={height} viewBox={`0 0 ${W} ${height}`} preserveAspectRatio="none">
        <Defs>
          <LinearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <Stop offset="0" stopColor={color} stopOpacity={0.30} />
            <Stop offset="1" stopColor={color} stopOpacity={0.02} />
          </LinearGradient>
        </Defs>
        <Path d={area} fill={`url(#${gradientId})`} />
        <Path d={line} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        <Line x1={PAD} x2={W - PAD} y1={last[1]} y2={last[1]} stroke={color} strokeOpacity={0.4} strokeWidth={1} strokeDasharray="4 4" />
      </Svg>
      <View style={[s.dot, {top: lastTop, backgroundColor: color}]} />
    </View>
  );
}

export function chartPriceText(v: number | null | undefined): string {
  return v == null || !Number.isFinite(v) ? "—" : fmtPrice(v);
}

const s = StyleSheet.create({
  placeholder: {
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.surface,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: colors.border
  },
  placeholderInner: {
    color: colors.muted2,
    fontSize: 8,
    fontWeight: "900",
    letterSpacing: 1
  },
  dot: {
    position: "absolute",
    right: 2,
    width: 8,
    height: 8,
    borderRadius: 4,
    borderWidth: 1,
    borderColor: colors.background
  }
});
