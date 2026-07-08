import type { TechnicalsResponse } from "@/lib/api";
import { fmtDecimal, fmtPct, fmtSigned } from "@/lib/formatters";
import { AnalyticalSeriesPanel } from "./AnalyticalSeriesPanel";
import { Tile, type MaKin, type TechDetail } from "./TechnicalsTiles";

const grid: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
  gap: 8,
};

const note: React.CSSProperties = {
  fontSize: 11,
  color: "var(--text-muted)",
  marginTop: 8,
  lineHeight: 1.55,
};

/** Scalar diagnostics that don't warrant their own time-series panel — current
 * readings with plain-English explanations (the histories live in the aligned
 * charts above). */
export function TechnicalsDetailPanels({ data }: { data: TechnicalsResponse }) {
  const d = (data.detail ?? {}) as TechDetail;
  const kin = d.kinematics ?? {};
  const sig = d.sigmoid ?? {};
  const dist = d.distribution ?? {};

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
        gap: 16,
      }}
    >
      <AnalyticalSeriesPanel
        title="Trend Reliability"
        subtitle="MA slope significance"
      >
        <div style={grid}>
          {(["sma20", "sma50", "sma200"] as const).map((k) => {
            const m: MaKin = kin[k] ?? null;
            const t = m?.tstat ?? null;
            return (
              <Tile
                key={k}
                label={`${k.toUpperCase()} t-stat`}
                value={fmtSigned(t as number | null, 1)}
                valueColor={
                  t == null
                    ? undefined
                    : Math.abs(t) < 2
                      ? "var(--text-muted)"
                      : t > 0
                        ? "var(--positive)"
                        : "var(--negative)"
                }
                sub={t != null && Math.abs(t) >= 2 ? "significant" : "weak"}
              />
            );
          })}
          <Tile
            label="Alignment"
            value={kin.alignment != null ? `${kin.alignment}/3` : "—"}
            valueColor={
              kin.alignment == null
                ? undefined
                : kin.alignment > 0
                  ? "var(--positive)"
                  : kin.alignment < 0
                    ? "var(--negative)"
                    : undefined
            }
            sub="MA stack order"
          />
        </div>
        <div style={note}>
          t-stat of each moving-average slope — how statistically reliable the
          trend is. |t| ≥ 2 means the slope is unlikely to be noise; the sign
          matches direction. Alignment counts how many of the three pairs
          (close&gt;SMA20&gt;SMA50&gt;SMA200) are in bullish order, −3…+3.
        </div>
      </AnalyticalSeriesPanel>

      <AnalyticalSeriesPanel
        title="Sigmoid Trend Maturity"
        subtitle="beats-linear guard · latest-only"
        headline={sig.valid ? (sig.phase ?? undefined) : undefined}
      >
        {sig.valid ? (
          <div style={grid}>
            <Tile label="k (steepness)" value={fmtDecimal(sig.k, 3)} />
            <Tile label="s = k·Δt" value={fmtSigned(sig.s, 2)} />
            <Tile
              label="R² sig / lin"
              value={`${fmtDecimal(sig.r2_sigmoid, 2)} / ${fmtDecimal(sig.r2_linear, 2)}`}
            />
          </div>
        ) : (
          <div style={{ color: "var(--text-muted)", fontSize: 12 }}>
            No S-curve structure (R²sig {fmtDecimal(sig.r2_sigmoid, 2)} ≤ R²lin{" "}
            {fmtDecimal(sig.r2_linear, 2)} + 0.05).
          </div>
        )}
        <div style={note}>
          Fits a logistic (S-)curve to the move since the last swing pivot and
          only reports it when it beats a straight line. Phase reads where on
          the S-curve price sits: EARLY → ACCELERATING → DECELERATING →
          SATURATED. It&apos;s a per-request fit, so there&apos;s no stored
          history to chart.
        </div>
      </AnalyticalSeriesPanel>

      <AnalyticalSeriesPanel
        title="Distribution Shape"
        subtitle="higher moments"
        headline={
          dist.rv20_z != null ? `RVz ${fmtSigned(dist.rv20_z, 2)}` : undefined
        }
      >
        <div style={grid}>
          <Tile label="RV20 z" value={fmtSigned(dist.rv20_z, 2)} sub="vs 1yr" />
          <Tile
            label="Vol-of-vol"
            value={fmtDecimal(dist.vol_of_vol, 3)}
            sub="σ of Δσ"
          />
          <Tile
            label="Jerk 20d"
            value={fmtDecimal(dist.jerk20, 4)}
            sub="accel of rets"
          />
          <Tile
            label="Skew 60d"
            value={fmtSigned(dist.skew60, 2)}
            sub="tail bias"
          />
          <Tile
            label="Kurt 60d"
            value={fmtDecimal(dist.kurt60, 2)}
            sub="fat tails"
          />
          <Tile
            label="RV20 (ann.)"
            value={fmtPct(dist.rv20)}
            sub="see vol chart"
          />
        </div>
        <div style={note}>
          Shape of the recent return distribution. RV20-z: is current realized
          vol high or low vs its own past year. Skew: negative = crash-prone
          left tail. Kurtosis: high = fat tails (jump risk). Jerk: how fast
          volatility itself is changing. The realized-vol time series is charted
          above.
        </div>
      </AnalyticalSeriesPanel>
    </div>
  );
}
