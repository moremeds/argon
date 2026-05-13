import { fmtDecimal, fmtPct, fmtSigned, toNum } from "@/lib/formatters";

export type VolHeader = {
  iv?: string | number | null | undefined;
  rv?: string | number | null | undefined;
  iv_rank?: string | number | null | undefined;
  iv_rank_1y?: string | number | null | undefined;
  iv_low_52w?: string | number | null | undefined;
  iv_high_52w?: string | number | null | undefined;
  rv_low_52w?: string | number | null | undefined;
  rv_high_52w?: string | number | null | undefined;
  iv_percentile_30d?: string | number | null | undefined;
  implied_move_30d_perc?: string | number | null | undefined;
  skew_25d?: string | number | null | undefined;
  vrp?: string | number | null | undefined;
  vrp_signal?: string;
  vrp_note?: string;
};

const tileStyle: React.CSSProperties = {
  background: "var(--bg-panel)",
  border: "1px solid var(--border-dim)",
  borderRadius: 4,
  padding: "12px 14px",
  display: "flex",
  flexDirection: "column",
  gap: 6,
  minWidth: 0,
};

const labelStyle: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: 10,
  letterSpacing: 1.5,
  textTransform: "uppercase",
  color: "var(--text-muted)",
};

const valueStyle: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontWeight: 700,
  fontSize: 22,
  color: "var(--text-primary)",
  lineHeight: 1,
};

const subStyle: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: 11,
  color: "var(--text-muted)",
};

function Tile({
  label,
  value,
  sub,
  valueColor,
}: {
  label: string;
  value: string;
  sub?: string;
  valueColor?: string;
}) {
  return (
    <div style={tileStyle}>
      <div style={labelStyle}>{label}</div>
      <div style={{ ...valueStyle, color: valueColor ?? valueStyle.color }}>
        {value}
      </div>
      <div style={subStyle}>{sub ?? " "}</div>
    </div>
  );
}

function vrpColor(v: number | null): string {
  if (v == null) return "var(--text-muted)";
  if (v > 0.05) return "var(--positive)";
  if (v < -0.05) return "var(--negative)";
  return "var(--text-muted)";
}

function signedColor(v: number | null): string {
  if (v == null) return "var(--text-primary)";
  if (v > 0) return "var(--positive)";
  if (v < 0) return "var(--negative)";
  return "var(--text-primary)";
}

function ivRankTercileColor(v: number | null): string {
  if (v == null) return "var(--text-primary)";
  if (v >= 66) return "var(--warning)";
  if (v <= 33) return "var(--positive)";
  return "var(--text-primary)";
}

function impliedMoveColor(v: number | null): string {
  if (v == null) return "var(--text-primary)";
  if (v > 0.1) return "var(--warning)";
  return "var(--text-primary)";
}

export function VolMetricsCard({ header }: { header: VolHeader }) {
  const iv = toNum(header.iv);
  const rv = toNum(header.rv);
  const ivRank = toNum(header.iv_rank);
  const ivRank1y = toNum(header.iv_rank_1y);
  const ivLow = toNum(header.iv_low_52w);
  const ivHigh = toNum(header.iv_high_52w);
  const rvLow = toNum(header.rv_low_52w);
  const rvHigh = toNum(header.rv_high_52w);
  const ivPctile30 = toNum(header.iv_percentile_30d);
  const impMove = toNum(header.implied_move_30d_perc);
  const skew = toNum(header.skew_25d);
  const vrp = toNum(header.vrp);

  const vrpSignalLabel = header.vrp_signal
    ? header.vrp_signal.replace("_", " ").toUpperCase()
    : "—";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(6, minmax(0, 1fr))",
          gap: 12,
        }}
      >
        <Tile
          label="VRP"
          value={vrp != null ? fmtSigned(vrp, 2) : "—"}
          sub={vrpSignalLabel}
          valueColor={vrpColor(vrp)}
        />
        <Tile label="IV (ATM)" value={fmtPct(iv, 1)} sub=" " />
        <Tile label="RV" value={fmtPct(rv, 1)} sub=" " />
        <Tile
          label="IV Rank"
          value={fmtDecimal(ivRank, 0)}
          sub={ivRank1y != null ? `1y rank ${Math.round(ivRank1y)}` : " "}
          valueColor={ivRankTercileColor(ivRank)}
        />
        <Tile
          label="IV %ile 30d"
          value={fmtDecimal(ivPctile30 != null ? ivPctile30 * 100 : null, 0)}
          sub=" "
        />
        <Tile
          label="Implied Move 30d"
          value={fmtPct(impMove, 1)}
          sub=" "
          valueColor={impliedMoveColor(impMove)}
        />
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(5, minmax(0, 1fr))",
          gap: 12,
        }}
      >
        <Tile label="IV 52w Low" value={fmtPct(ivLow, 1)} sub=" " />
        <Tile label="IV 52w High" value={fmtPct(ivHigh, 1)} sub=" " />
        <Tile label="RV 52w Low" value={fmtPct(rvLow, 1)} sub=" " />
        <Tile label="RV 52w High" value={fmtPct(rvHigh, 1)} sub=" " />
        <Tile
          label="Skew 25Δ"
          value={fmtSigned(skew, 4)}
          sub=" "
          valueColor={signedColor(skew)}
        />
      </div>

      {header.vrp_note && (
        <div
          style={{
            padding: 10,
            border: "1px solid var(--border-dim)",
            borderRadius: 4,
            background: "var(--bg-panel)",
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            color: "var(--text-secondary)",
            whiteSpace: "pre-wrap",
          }}
        >
          {header.vrp_note}
        </div>
      )}
    </div>
  );
}
