"use client";

import { fmtDecimal, fmtSigned, toNum } from "@/lib/formatters";

import { AnalyticalSeriesPanel } from "./AnalyticalSeriesPanel";

type Posture = {
  rr_25d?: string | number | null;
  rr_z_180d?: string | number | null;
  rr_pct_252d?: string | number | null;
  deviation_class: string;
  drive_class: string;
  borrow_flag: string;
  regime: string;
};

export function deviationColor(cls: string): string {
  if (cls === "RICH") return "var(--warning)";
  if (cls === "CHEAP") return "var(--positive)";
  return "var(--text-primary)";
}

const tile: React.CSSProperties = {
  background: "var(--bg-panel)",
  border: "1px solid var(--border-dim)",
  borderRadius: 4,
  padding: "12px 14px",
  display: "flex",
  flexDirection: "column",
  gap: 6,
};
const label: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: 10,
  letterSpacing: 1.5,
  textTransform: "uppercase",
  color: "var(--text-muted)",
};
const value: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontWeight: 700,
  fontSize: 22,
  color: "var(--text-primary)",
  lineHeight: 1,
};

export function SkewPostureTiles({ p }: { p: Posture }) {
  const rr = toNum(p.rr_25d);
  const z = toNum(p.rr_z_180d);
  const pct = toNum(p.rr_pct_252d);
  return (
    <AnalyticalSeriesPanel title="Posture" subtitle="VS OWN BASELINE">
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))",
          gap: 10,
        }}
      >
        <div style={tile}>
          <div style={label}>RR 25Δ</div>
          <div style={value}>{rr != null ? fmtSigned(rr, 4) : "—"}</div>
          <div style={label}>put−call IV</div>
        </div>
        <div style={tile}>
          <div style={label}>Deviation</div>
          <div style={{ ...value, color: deviationColor(p.deviation_class) }}>
            {p.deviation_class}
          </div>
          <div style={label}>
            z {z != null ? fmtSigned(z, 2) : "—"} · pct{" "}
            {pct != null ? fmtDecimal(pct, 0) : "—"}
          </div>
        </div>
        <div style={tile}>
          <div style={label}>Drive</div>
          <div style={value}>{p.drive_class}</div>
          <div style={label}>regime {p.regime}</div>
        </div>
        <div style={tile}>
          <div style={label}>Borrow</div>
          <div style={value}>{p.borrow_flag}</div>
          <div style={label}>JFE confound gate</div>
        </div>
      </div>
    </AnalyticalSeriesPanel>
  );
}
