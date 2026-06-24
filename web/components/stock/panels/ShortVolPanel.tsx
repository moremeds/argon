import type { components } from "@/lib/types";
import { toNum } from "@/lib/formatters";

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

const pct = (x: number | null) =>
  x == null ? "—" : `${(x * 100).toFixed(1)}%`;
const f = (x: number | null, d = 2) => (x == null ? "—" : x.toFixed(d));

export function ShortVolPanel({ report }: { report: Report }) {
  const s = report.short_vol;

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
        EOD SNAPSHOT
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
  const reasons = trade
    ? [
        `vrp_z ${f(toNum(s.vrp_z))} · weight ${f(toNum(s.weight))} (size)`,
        `Sell ${f(toNum(s.short_put), 0)} / buy ${f(toNum(s.long_put), 0)} put`,
        `Credit ${f(toNum(s.credit))} · max loss ${f(toNum(s.max_loss))} per spread`,
      ]
    : [
        `vrp_z ${f(toNum(s.vrp_z))} · weight ${f(toNum(s.weight))}`,
        `IV ${pct(toNum(s.iv))} / RV20 ${pct(toNum(s.rv20))}`,
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
      </div>
    </div>
  );
}
