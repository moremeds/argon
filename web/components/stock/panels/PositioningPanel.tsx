import type { components } from "@/lib/types";
import { fmtDecimal, fmtSigned, toNum } from "@/lib/formatters";

type Positioning = components["schemas"]["PositioningSnapshot"];

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

function squeezeColor(label: string): string {
  if (label === "HIGH") return "var(--negative)";
  if (label === "ELEVATED") return "var(--warning)";
  if (label === "LOW") return "var(--positive)";
  return "var(--text-muted)";
}

function tiltColor(tilt: string): string {
  if (tilt === "BUYING") return "var(--positive)";
  if (tilt === "SELLING") return "var(--negative)";
  return "var(--text-muted)";
}

function Row({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color?: string;
}) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "baseline",
        gap: 12,
      }}
    >
      <span style={{ color: "var(--text-muted)", fontSize: 11 }}>{label}</span>
      <span
        style={{
          color: color ?? "var(--text-secondary)",
          fontSize: 12,
          textAlign: "right",
        }}
      >
        {value}
      </span>
    </div>
  );
}

// si_pct_float is a fraction (0.29 == 29%); si_fee_rate is already a percent.
function pctFromFraction(v: unknown): string {
  const n = toNum(v);
  return n == null ? "—" : `${fmtDecimal(n * 100, 1)}%`;
}

function pct(v: unknown): string {
  const n = toNum(v);
  return n == null ? "—" : `${fmtDecimal(n, 1)}%`;
}

function usd(v: unknown): string {
  const n = toNum(v);
  if (n == null) return "—";
  const abs = Math.abs(n);
  const sign = n < 0 ? "-" : "";
  if (abs >= 1e9) return `${sign}$${fmtDecimal(abs / 1e9, 2)}B`;
  if (abs >= 1e6) return `${sign}$${fmtDecimal(abs / 1e6, 2)}M`;
  if (abs >= 1e3) return `${sign}$${fmtDecimal(abs / 1e3, 1)}K`;
  return `${sign}$${fmtDecimal(abs, 0)}`;
}

export function PositioningPanel({ data }: { data: Positioning }) {
  const badge = data.snapshot_date
    ? `EOD · ${data.snapshot_date}`
    : "POSITIONING";

  const header = (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        marginBottom: 12,
      }}
    >
      <span style={labelStyle}>POSITIONING · {data.ticker}</span>
      <span style={{ ...labelStyle, fontSize: 9, letterSpacing: 0.5 }}>
        {badge}
      </span>
    </div>
  );

  if (!data.available) {
    return (
      <div style={panelStyle} data-testid="positioning-panel">
        {header}
        <div style={{ color: "var(--text-muted)", fontSize: 12 }}>
          No positioning snapshot banked yet.
        </div>
      </div>
    );
  }

  const s = data.signals;
  const upside = toNum(s.analyst_implied_upside_pct);
  const baseRate = toNum(s.er_positive_base_rate);

  return (
    <div style={panelStyle} data-testid="positioning-panel">
      {header}

      <div
        data-testid="positioning-squeeze"
        style={{
          color: squeezeColor(s.squeeze_label),
          fontSize: 24,
          fontWeight: 700,
          letterSpacing: 1,
          marginBottom: 2,
        }}
      >
        SQUEEZE {s.squeeze_label}
      </div>
      <div
        style={{ color: "var(--text-muted)", fontSize: 11, marginBottom: 12 }}
      >
        {s.squeeze_score != null ? `score ${s.squeeze_score}/6 · ` : ""}
        SI {pctFromFraction(data.si_pct_float)} float · DTC{" "}
        {fmtDecimal(toNum(data.si_days_to_cover), 1)}d · fee{" "}
        {pct(data.si_fee_rate)}
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <Row
          label="Insider net flow"
          value={`${usd(data.insider_net_flow)} · ${s.insider_tilt}`}
          color={tiltColor(s.insider_tilt)}
        />
        <Row
          label="Analyst implied upside"
          value={upside == null ? "—" : `${fmtSigned(upside, 1)}%`}
          color={
            upside == null
              ? undefined
              : upside >= 0
                ? "var(--positive)"
                : "var(--negative)"
          }
        />
        <Row
          label="Analyst B/H/S"
          value={
            data.analyst_buy == null &&
            data.analyst_hold == null &&
            data.analyst_sell == null
              ? "—"
              : `${data.analyst_buy ?? 0} / ${data.analyst_hold ?? 0} / ${data.analyst_sell ?? 0}`
          }
        />
        <Row
          label="Avg target"
          value={
            toNum(data.analyst_target_avg) == null
              ? "—"
              : `$${fmtDecimal(toNum(data.analyst_target_avg), 2)}`
          }
        />
        <Row
          label="Pre-ER positive rate"
          value={
            baseRate == null
              ? "—"
              : `${fmtDecimal(baseRate * 100, 0)}% (${data.earn_reactions_positive ?? 0}/${data.earn_reactions_total ?? 0})`
          }
        />
        <Row
          label="Institutions"
          value={
            data.inst_holder_count == null
              ? "—"
              : `${data.inst_holder_count} holders · ${usd(data.inst_total_value)}`
          }
        />
      </div>

      {data.next_er_date ? (
        <div
          style={{
            marginTop: 12,
            paddingTop: 10,
            borderTop: "1px solid var(--border-dim)",
            color: "var(--text-muted)",
            fontSize: 11,
          }}
        >
          Next earnings {data.next_er_date}
          {s.days_to_next_er != null ? ` · ${s.days_to_next_er}d out` : ""}
        </div>
      ) : null}
    </div>
  );
}
