import { linearScale } from "@/lib/svgChart";
import type { TechnicalsResponse } from "@/lib/api";
import { AnalyticalSeriesPanel } from "./AnalyticalSeriesPanel";

const CW = 900;
const H = 190;
const PAD = { l: 34, r: 16, t: 12, b: 26 };
const WINDOW = 60; // trailing daily returns
const NBINS = 21;

export type Bins = {
  edges: number[];
  counts: number[];
  mean: number;
  sd: number;
};

// Pure: bin `returns` into `nbins` over [mean-3.5σ, mean+3.5σ] (outliers clamp
// to the edge bins), returning bin edges, counts, and the sample moments.
export function returnBins(returns: number[], nbins = NBINS): Bins {
  const empty: Bins = {
    edges: Array.from({ length: nbins + 1 }, (_, i) => i),
    counts: Array(nbins).fill(0),
    mean: 0,
    sd: 0,
  };
  const n = returns.length;
  if (n < 2) return empty;
  const mean = returns.reduce((a, c) => a + c, 0) / n;
  const variance = returns.reduce((a, c) => a + (c - mean) ** 2, 0) / (n - 1);
  const sd = Math.sqrt(variance);
  if (!(sd > 0)) return { ...empty, mean };
  const lo = mean - 3.5 * sd;
  const hi = mean + 3.5 * sd;
  const w = (hi - lo) / nbins;
  const edges = Array.from({ length: nbins + 1 }, (_, i) => lo + i * w);
  const counts = Array(nbins).fill(0);
  for (const r of returns) {
    let idx = Math.floor((r - lo) / w);
    if (idx < 0) idx = 0;
    if (idx >= nbins) idx = nbins - 1;
    counts[idx] += 1;
  }
  return { edges, counts, mean, sd };
}

function normPdf(x: number, mean: number, sd: number): number {
  const z = (x - mean) / sd;
  return Math.exp(-0.5 * z * z) / (sd * Math.sqrt(2 * Math.PI));
}

export function ReturnHistogram({ data }: { data: TechnicalsResponse }) {
  const closes = (data.series ?? [])
    .map((r) => r.close)
    .filter((v): v is number => v != null);
  const rets: number[] = [];
  for (let i = 1; i < closes.length; i++) {
    const p = closes[i - 1];
    if (p) rets.push(closes[i] / p - 1);
  }
  const window = rets.slice(-WINDOW);
  const { edges, counts, mean, sd } = returnBins(window, NBINS);
  const n = window.length;

  if (n < 20 || !(sd > 0)) {
    return (
      <AnalyticalSeriesPanel title="Return Distribution" subtitle="shape">
        <div style={{ color: "var(--text-muted)", fontSize: 12, padding: 8 }}>
          Not enough history for the return distribution.
        </div>
      </AnalyticalSeriesPanel>
    );
  }

  const skew =
    (n / ((n - 1) * (n - 2))) *
    window.reduce((a, c) => a + ((c - mean) / sd) ** 3, 0);

  const lo = edges[0];
  const hi = edges[edges.length - 1];
  const x = linearScale([lo, hi], [PAD.l, CW - PAD.r]);
  const w = (hi - lo) / NBINS;
  const maxCount = Math.max(1, ...counts);
  const y = linearScale([0, maxCount * 1.12], [H - PAD.b, PAD.t]);

  // Normal overlay in count units: expected count per bin = n * binWidth * pdf.
  const curve: string = Array.from({ length: 121 }, (_, i) => {
    const xv = lo + ((hi - lo) * i) / 120;
    const c = n * w * normPdf(xv, mean, sd);
    return `${i === 0 ? "M" : "L"}${x(xv).toFixed(1)},${y(c).toFixed(1)}`;
  }).join(" ");

  const sigTicks = [-3, -2, -1, 0, 1, 2, 3];

  return (
    <AnalyticalSeriesPanel
      title="Return Distribution"
      subtitle={`daily returns · last ${n}d`}
      headline={`skew ${skew >= 0 ? "+" : ""}${skew.toFixed(2)}`}
    >
      <svg
        viewBox={`0 0 ${CW} ${H}`}
        width="100%"
        role="img"
        style={{ display: "block" }}
      >
        <title>Return distribution histogram with normal overlay</title>
        {/* baseline */}
        <line
          x1={PAD.l}
          x2={CW - PAD.r}
          y1={y(0)}
          y2={y(0)}
          stroke="var(--border-dim)"
          strokeWidth={0.6}
        />
        {counts.map((c, i) => {
          const center = (edges[i] + edges[i + 1]) / 2;
          const zc = (center - mean) / sd;
          // Flag the tails (>|2σ|) so fat-tail / jump risk is visible.
          const fill =
            Math.abs(zc) >= 2 ? "var(--negative)" : "var(--accent-vol)";
          return (
            <rect
              key={i}
              x={x(edges[i]) + 0.6}
              y={y(c)}
              width={Math.max(0.5, x(edges[i + 1]) - x(edges[i]) - 1.2)}
              height={Math.max(0, y(0) - y(c))}
              fill={fill}
              opacity={0.55}
            />
          );
        })}
        {/* normal overlay */}
        <path
          d={curve}
          fill="none"
          stroke="var(--text-secondary)"
          strokeWidth={1.4}
        />
        {/* mean line */}
        <line
          x1={x(mean)}
          x2={x(mean)}
          y1={PAD.t}
          y2={y(0)}
          stroke="var(--text-muted)"
          strokeWidth={0.6}
          strokeDasharray="3 3"
        />
        {sigTicks.map((s) => {
          const xv = mean + s * sd;
          if (xv < lo || xv > hi) return null;
          return (
            <text
              key={s}
              x={x(xv)}
              y={H - 8}
              fontSize={9}
              fill="var(--text-muted)"
              textAnchor="middle"
              fontFamily="var(--font-mono)"
            >
              {s === 0 ? "0" : `${s > 0 ? "+" : ""}${s}σ`}
            </text>
          );
        })}
      </svg>
      <div style={{ marginTop: 6, display: "flex", gap: 16 }}>
        <Legend color="var(--accent-vol)" label="observed" />
        <Legend color="var(--text-secondary)" label="normal" line />
        <Legend color="var(--negative)" label="tails > 2σ" />
      </div>
      <div
        style={{
          fontSize: 11,
          color: "var(--text-muted)",
          marginTop: 8,
          lineHeight: 1.55,
        }}
      >
        Histogram of the last {n} daily returns vs a normal with the same mean
        and σ. A left-leaning mass (negative skew) means crash-prone downside; a
        peakier center with fatter tails than the curve means jump risk
        (kurtosis). Bars beyond ±2σ are the tails.
      </div>
    </AnalyticalSeriesPanel>
  );
}

function Legend({
  color,
  label,
  line,
}: {
  color: string;
  label: string;
  line?: boolean;
}) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
      <span
        style={{
          width: 14,
          height: line ? 2 : 9,
          background: color,
          opacity: line ? 1 : 0.55,
          display: "inline-block",
          borderRadius: 1,
        }}
      />
      <span style={{ fontSize: 10, color: "var(--text-muted)" }}>{label}</span>
    </span>
  );
}
