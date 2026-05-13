import { fmtDecimal, fmtPct, fmtSigned, toNum } from "@/lib/formatters";
import { Metric, MetricGrid } from "./MetricGrid";

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

export function VolMetricsCard({ header }: { header: VolHeader }) {
  const vrpNum = toNum(header.vrp);
  const badgeColor =
    vrpNum != null && vrpNum > 0.05
      ? "var(--positive)"
      : vrpNum != null && vrpNum < -0.05
        ? "var(--negative)"
        : "var(--text-muted)";

  return (
    <div
      style={{
        background: "var(--bg-panel)",
        border: "1px solid var(--border-dim)",
        borderRadius: 4,
        padding: 16,
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 12,
        }}
      >
        <h3
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            color: "var(--text-secondary)",
            letterSpacing: 1,
            textTransform: "uppercase",
            margin: 0,
          }}
        >
          Volatility
        </h3>
        {header.vrp_signal && (
          <span
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 11,
              padding: "2px 8px",
              border: `1px solid ${badgeColor}`,
              borderRadius: 2,
              color: badgeColor,
              letterSpacing: 1,
            }}
          >
            VRP {fmtSigned(vrpNum, 2)}{" "}
            {header.vrp_signal.replace("_", " ").toUpperCase()}
          </span>
        )}
      </div>
      <MetricGrid cols={4}>
        <Metric label="IV (ATM)" value={fmtPct(toNum(header.iv), 1)} />
        <Metric label="RV" value={fmtPct(toNum(header.rv), 1)} />
        <Metric label="IV Rank" value={fmtDecimal(toNum(header.iv_rank), 0)} />
        <Metric
          label="IV Rank 1y"
          value={fmtDecimal(toNum(header.iv_rank_1y), 0)}
        />
        <Metric
          label="IV 52w Low"
          value={fmtPct(toNum(header.iv_low_52w), 1)}
        />
        <Metric
          label="IV 52w High"
          value={fmtPct(toNum(header.iv_high_52w), 1)}
        />
        <Metric
          label="RV 52w Low"
          value={fmtPct(toNum(header.rv_low_52w), 1)}
        />
        <Metric
          label="RV 52w High"
          value={fmtPct(toNum(header.rv_high_52w), 1)}
        />
        <Metric
          label="IV %ile 30d"
          value={fmtDecimal(toNum(header.iv_percentile_30d), 0)}
        />
        <Metric
          label="Implied Move 30d"
          value={fmtPct(toNum(header.implied_move_30d_perc), 1)}
        />
        <Metric label="Skew 25Δ" value={fmtSigned(toNum(header.skew_25d), 4)} />
      </MetricGrid>
      {header.vrp_note && (
        <div
          style={{
            marginTop: 12,
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
