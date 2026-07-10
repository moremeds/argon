import type { CSSProperties, ReactNode } from "react";

const tileStyle: CSSProperties = {
  background: "var(--bg-panel)",
  border: "1px solid var(--border-dim)",
  borderRadius: 4,
  padding: "10px 12px",
  fontFamily: "var(--font-mono)",
  minWidth: 0,
};
const labelStyle: CSSProperties = {
  fontSize: 10,
  letterSpacing: 1.5,
  textTransform: "uppercase",
  color: "var(--text-muted)",
  whiteSpace: "nowrap",
  overflow: "hidden",
  textOverflow: "ellipsis",
};
const valueStyle: CSSProperties = {
  fontSize: 22,
  fontWeight: 700,
  color: "var(--text-primary)",
  fontVariantNumeric: "tabular-nums",
};
const subStyle: CSSProperties = {
  fontSize: 11,
  color: "var(--text-secondary)",
  whiteSpace: "nowrap",
  overflow: "hidden",
  textOverflow: "ellipsis",
};

export function Tile({
  label,
  value,
  sub,
  valueColor,
  corner,
}: {
  label: string;
  value: string;
  sub?: string;
  valueColor?: string;
  corner?: ReactNode;
}) {
  return (
    <div style={{ ...tileStyle, position: "relative" }}>
      {corner != null && (
        <div style={{ position: "absolute", top: 8, right: 10 }}>{corner}</div>
      )}
      <div style={labelStyle}>{label}</div>
      <div style={{ ...valueStyle, color: valueColor ?? valueStyle.color }}>
        {value}
      </div>
      <div style={subStyle}>{sub ?? " "}</div>
    </div>
  );
}

/** Latest-row `detail` JSONB shape (mirrors build_technical_snapshot). */
export type TechDetail = {
  bars_n?: number | null;
  dist_pct?: number | null;
  composite?: number | null;
  kinematics?: {
    alignment?: number | null;
    sma20?: MaKin;
    sma50?: MaKin;
    sma200?: MaKin;
  } | null;
  sigmoid?: {
    valid?: boolean;
    phase?: string | null;
    k?: number | null;
    s?: number | null;
    r2_sigmoid?: number | null;
    r2_linear?: number | null;
  } | null;
  distribution?: {
    rv20?: number | null;
    rv20_z?: number | null;
    vol_of_vol?: number | null;
    skew60?: number | null;
    kurt60?: number | null;
    jerk20?: number | null;
  } | null;
  rsi?: {
    rsi14?: number | null;
    rsi_z?: number | null;
    rsi_slope5?: number | null;
    divergence?: { type?: string; rsi_gap?: number } | null;
  } | null;
  macd?: { hist_atr?: number | null; hist_atr_slope3?: number | null } | null;
  rs?: {
    ratio?: number | null;
    ma60?: number | null;
    ma200?: number | null;
    trend?: string | null;
    n?: number | null;
  } | null;
};

export type MaKin = {
  slope_atr?: number | null;
  curv_atr?: number | null;
  tstat?: number | null;
} | null;
