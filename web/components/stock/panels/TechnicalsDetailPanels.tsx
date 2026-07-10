import type { TechnicalsResponse } from "@/lib/api";
import { fmtDecimal, fmtPct, fmtSigned } from "@/lib/formatters";
import { AnalyticalSeriesPanel } from "./AnalyticalSeriesPanel";
import { Tile, type TechDetail } from "./TechnicalsTiles";
import { linearScale, pathFromPoints, type Point } from "@/lib/svgChart";

/** The per-request sigmoid fit, drawn as actual-price (muted) vs the fitted
 * logistic (accent). Both arrays are the same length (segment since the last
 * pivot); values are the real fitted logistic — nothing synthetic. */
export function SigmoidFitChart({
  actual,
  fit,
}: {
  actual: number[];
  fit: number[];
}) {
  const n = Math.min(actual.length, fit.length);
  if (n < 2) return null;
  const W = 400;
  const H = 130;
  const P = 8; // uniform padding
  const all = [...actual.slice(0, n), ...fit.slice(0, n)].filter(
    Number.isFinite,
  );
  const sx = linearScale([0, n - 1], [P, W - P]);
  const sy = linearScale([Math.min(...all), Math.max(...all)], [H - P, P]);
  const pts = (arr: number[]): Point[] =>
    arr.slice(0, n).map((v, i) => [sx(i), sy(v)]);
  return (
    <svg
      role="img"
      viewBox={`0 0 ${W} ${H}`}
      style={{ width: "100%", height: "auto" }}
    >
      <title>
        Price since the last pivot (muted) vs the fitted logistic (accent)
      </title>
      <path
        d={pathFromPoints(pts(actual))}
        fill="none"
        stroke="var(--text-secondary)"
        strokeWidth={1}
        opacity={0.5}
      />
      <path
        d={pathFromPoints(pts(fit))}
        fill="none"
        stroke="var(--accent-vivid)"
        strokeWidth={1.75}
      />
      <circle
        cx={sx(n - 1)}
        cy={sy(actual[n - 1])}
        r={2.5}
        fill="var(--accent-vivid)"
      />
    </svg>
  );
}

/** Why the sigmoid fit was rejected, in plain English. Derived from the two R²
 * values the payload already carries + the backend's validity gate
 * (r2_sig ≥ 0.80 AND r2_sig ≥ r2_lin + 0.05 AND k > 0). The old copy hardcoded
 * only the beats-linear clause, so on an absolute-fit miss it printed the false
 * "0.31 ≤ 0.05 + 0.05" — this names the clause that actually failed.
 * ponytail: the 0.80 mirrors fit_sigmoid()'s gate — copy-only; drift here just
 * softens wording, never a data bug. */
export function sigmoidRejectReason(
  r2Sig: number | null | undefined,
  r2Lin: number | null | undefined,
): string {
  const pct = (x: number) => `${Math.round(x * 100)}%`;
  if (r2Sig == null)
    return "not enough clean history since the last pivot to fit a curve";
  if (r2Sig < 0.8)
    return `the move is too choppy for a clean S-curve — the fit explains only ${pct(r2Sig)} of it (an S-curve needs ≥ 80%)`;
  if (r2Lin != null && r2Sig < r2Lin + 0.05)
    return `a straight line already explains it about as well (S-curve ${pct(r2Sig)} vs linear ${pct(r2Lin)}) — the trend is roughly linear, not an S`;
  return "the fitted curve bends the wrong way (decelerating into the pivot)";
}

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
      {/* Trend Reliability (MA-slope t-stats) is folded into the MA-Kinematics
          chart above — line weight + legend + ALIGN badge — so it's no longer a
          standalone panel. */}
      <AnalyticalSeriesPanel
        title="Sigmoid Trend Maturity"
        subtitle="beats-linear guard · latest-only"
        headline={sig.valid ? (sig.phase ?? undefined) : undefined}
      >
        {sig.valid ? (
          <>
            <div style={grid}>
              <Tile label="k (steepness)" value={fmtDecimal(sig.k, 3)} />
              <Tile label="s = k·Δt" value={fmtSigned(sig.s, 2)} />
              <Tile
                label="R² sig / lin"
                value={`${fmtDecimal(sig.r2_sigmoid, 2)} / ${fmtDecimal(sig.r2_linear, 2)}`}
              />
            </div>
            {sig.actual && sig.fit ? (
              <div style={{ marginTop: 10 }}>
                <SigmoidFitChart actual={sig.actual} fit={sig.fit} />
              </div>
            ) : null}
          </>
        ) : (
          <div style={{ color: "var(--text-muted)", fontSize: 12 }}>
            No S-curve reported —{" "}
            {sigmoidRejectReason(sig.r2_sigmoid, sig.r2_linear)}. This is a
            normal read for linear or choppy trends, not an error.
          </div>
        )}
        <div style={note}>
          <strong style={{ color: "var(--text-secondary)" }}>
            How to read:
          </strong>{" "}
          an S-curve (logistic) traces a move that starts slow, accelerates,
          then flattens as it matures. We fit one to price since the last swing
          pivot and show it only when it clearly beats a straight line (≥ 80%
          fit). When shown, the muted line is actual price and the bright line
          is the fit — the dot marks today. <strong>Phase</strong> says where on
          the curve price sits: EARLY (base) → ACCELERATING (steepest climb) →
          DECELERATING (rolling over) → SATURATED (flat top). <strong>k</strong>{" "}
          = steepness, <strong>s = k·Δt</strong> = how far along the curve,{" "}
          <strong>R² sig/lin</strong> = fit quality vs a straight line. No curve
          just means the trend is linear or too choppy to fit — not a problem.
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
