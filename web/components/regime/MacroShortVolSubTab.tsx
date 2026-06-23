"use client";

import { useVrpMacroLive } from "@/lib/regime/useVrpMacroLive";

const label: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: 10,
  letterSpacing: 1.5,
  textTransform: "uppercase",
  color: "var(--text-muted)",
};
const value: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: 14,
  textAlign: "right",
  fontVariantNumeric: "tabular-nums",
};

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 24 }}>
      <span style={label}>{k}</span>
      <span style={value}>{v}</span>
    </div>
  );
}

export default function MacroShortVolSubTab() {
  const { data, loading } = useVrpMacroLive();
  if (loading)
    return (
      <div style={{ padding: 16, color: "var(--text-muted)" }}>Loading…</div>
    );
  if (!data?.signal)
    return (
      <div style={{ padding: 16, color: "var(--text-muted)" }}>
        No macro short-vol signal yet (no live quote and no EOD snapshot).
      </div>
    );

  const s = data.signal;
  const trade = s.action === "TRADE";
  const pct = (x: number | null | undefined) =>
    x == null ? "—" : `${(x * 100).toFixed(1)}%`;

  return (
    <div
      style={{ padding: 16, display: "flex", flexDirection: "column", gap: 12 }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <span style={{ ...label, fontSize: 11 }}>Macro Short-Vol · SPX</span>
        <span style={{ ...label, fontSize: 9 }}>
          {data.basis === "live"
            ? `live · ${data.active_source ?? ""}`
            : "EOD snapshot"}
        </span>
      </div>

      <div
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 26,
          fontWeight: 700,
          color: trade ? "var(--positive, #34d399)" : "var(--text-muted)",
        }}
      >
        {s.action}
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <Row k="vrp_z" v={s.vrp_z == null ? "—" : s.vrp_z.toFixed(2)} />
        <Row k="weight" v={s.weight.toFixed(2)} />
        <Row k="IV / RV20" v={`${pct(s.iv)} / ${pct(s.rv20)}`} />
        {trade && (
          <>
            <Row
              k="short / wing"
              v={`${s.short_put?.toFixed(0) ?? "—"} / ${s.long_put?.toFixed(0) ?? "—"}`}
            />
            <Row
              k="credit / maxloss"
              v={`${s.credit?.toFixed(2) ?? "—"} / ${s.max_loss?.toFixed(2) ?? "—"}`}
            />
          </>
        )}
        {s.bt_sharpe != null && (
          <Row k="backtest Sharpe" v={s.bt_sharpe.toFixed(2)} />
        )}
      </div>

      <p
        style={{
          ...label,
          fontSize: 10,
          lineHeight: 1.5,
          textTransform: "none",
          letterSpacing: 0,
        }}
      >
        Bull put spread, {s.short_delta}Δ / {s.wing_delta}Δ, ~{s.hold_days}-day
        hold, weekly, vrp-z gated. Flat-vol modeled credit (conservative floor).
        {trade ? "" : " Vol not rich enough — stand aside."}
      </p>
    </div>
  );
}
