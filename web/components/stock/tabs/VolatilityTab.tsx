import type { components } from "@/lib/types";
import { MetricGrid, Metric } from "../panels/MetricGrid";
import { fmtPct, fmtDecimal, fmtSigned, toNum } from "@/lib/formatters";

type Report = components["schemas"]["SingleStockReport"];

export function VolatilityTab({ report }: { report: Report }) {
  const v = report.volatility;
  return (
    <div>
      <h3
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          color: "var(--text-secondary)",
          letterSpacing: 1,
          textTransform: "uppercase",
        }}
      >
        Volatility Surface
      </h3>
      <MetricGrid cols={4}>
        <Metric label="IV (ATM)" value={fmtPct(toNum(v.iv), 1)} />
        <Metric label="RV" value={fmtPct(toNum(v.rv), 1)} />
        <Metric label="IV Rank" value={fmtDecimal(toNum(v.iv_rank), 0)} />
        <Metric label="IV Rank 1y" value={fmtDecimal(toNum(v.iv_rank_1y), 0)} />
        <Metric label="IV 52w Low" value={fmtPct(toNum(v.iv_low_52w), 1)} />
        <Metric label="IV 52w High" value={fmtPct(toNum(v.iv_high_52w), 1)} />
        <Metric label="RV 52w Low" value={fmtPct(toNum(v.rv_low_52w), 1)} />
        <Metric label="RV 52w High" value={fmtPct(toNum(v.rv_high_52w), 1)} />
        <Metric
          label="IV %ile 30d"
          value={fmtDecimal(toNum(v.iv_percentile_30d), 0)}
        />
        <Metric
          label="Implied Move 30d"
          value={fmtPct(toNum(v.implied_move_30d_perc), 1)}
        />
        <Metric label="Skew 25Δ" value={fmtSigned(toNum(v.skew_25d), 4)} />
      </MetricGrid>

      {v.term_dte_to_iv.length > 0 && (
        <>
          <h3
            style={{
              marginTop: 24,
              fontFamily: "var(--font-mono)",
              fontSize: 10,
              color: "var(--text-secondary)",
              letterSpacing: 1,
              textTransform: "uppercase",
            }}
          >
            Term Structure (DTE → IV)
          </h3>
          <div
            style={{
              display: "flex",
              gap: 16,
              fontFamily: "var(--font-mono)",
              fontSize: 11,
              flexWrap: "wrap",
            }}
          >
            {v.term_dte_to_iv.map(([dte, iv]) => (
              <div key={dte}>
                <span style={{ color: "var(--text-muted)" }}>{dte}d </span>
                <span>{fmtPct(toNum(iv), 1)}</span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
