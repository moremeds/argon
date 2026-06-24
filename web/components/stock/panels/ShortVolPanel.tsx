import type { components } from "@/lib/types";
import { fmtDecimal, fmtPct, toNum } from "@/lib/formatters";

type Report = components["schemas"]["SingleStockReport"];

const panelStyle: React.CSSProperties = {
  background: "var(--bg-panel)",
  border: "1px solid var(--border-dim)",
  borderRadius: 4,
  padding: 16,
  fontFamily: "var(--font-mono)",
  minWidth: 0,
};

const labelStyle: React.CSSProperties = {
  fontSize: 10,
  letterSpacing: 1.5,
  textTransform: "uppercase",
  color: "var(--text-muted)",
};

export function ShortVolPanel({ report }: { report: Report }) {
  const s = report.short_vol;
  // Show the row's actual date so a stale vrp_daily read (pipeline gap) is visible,
  // rather than a hardcoded badge that looks identically fresh.
  const badge = s ? `EOD · ${s.as_of}` : "EOD SNAPSHOT";

  const header = (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        marginBottom: 12,
      }}
    >
      <span style={labelStyle}>SHORT-VOL · {report.ticker}</span>
      <span style={{ ...labelStyle, fontSize: 9, letterSpacing: 0.5 }}>
        {badge}
      </span>
    </div>
  );

  if (!s) {
    return (
      <div style={panelStyle} data-testid="short-vol-panel">
        {header}
        <div style={{ color: "var(--text-muted)", fontSize: 12 }}>
          No vol data yet.
        </div>
      </div>
    );
  }

  const trade = s.action === "TRADE";
  const color = trade ? "var(--positive)" : "var(--text-muted)";
  // weight is structurally pinned (1.0 on every TRADE, 0 on every SKIP), so it carries
  // no information — vrp_z is the real richness signal.
  const reasons = trade
    ? [
        `vrp_z ${fmtDecimal(toNum(s.vrp_z), 2)}`,
        `Sell ${fmtDecimal(toNum(s.short_put), 0)} / buy ${fmtDecimal(toNum(s.long_put), 0)} put`,
        `Credit ${fmtDecimal(toNum(s.credit), 2)} · max loss ${fmtDecimal(toNum(s.max_loss), 2)} per spread`,
      ]
    : [
        `vrp_z ${fmtDecimal(toNum(s.vrp_z), 2)}`,
        `IV ${fmtPct(toNum(s.iv), 1)} / RV20 ${fmtPct(toNum(s.rv20), 1)}`,
      ];

  return (
    <div style={panelStyle} data-testid="short-vol-panel">
      {header}
      <div
        data-testid="short-vol-action"
        style={{
          color,
          fontSize: 28,
          fontWeight: 700,
          letterSpacing: 1,
          marginBottom: 10,
        }}
      >
        {s.action}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {reasons.map((r, i) => (
          <div key={i} style={{ color: "var(--text-secondary)", fontSize: 12 }}>
            {r}
          </div>
        ))}
        {!trade && s.skip_reason ? (
          <div style={{ color: "var(--text-muted)", fontSize: 12 }}>
            {s.skip_reason}
          </div>
        ) : null}
      </div>
      <div
        style={{
          marginTop: 12,
          paddingTop: 10,
          borderTop: "1px solid var(--border-dim)",
          color: "var(--text-muted)",
          fontSize: 11,
        }}
      >
        Bull put spread {toNum(s.short_delta)}Δ/{toNum(s.wing_delta)}Δ · ~
        {s.hold_days}d hold
        {toNum(s.spot) != null ? ` · spot ${fmtDecimal(toNum(s.spot), 2)}` : ""}
      </div>
    </div>
  );
}
