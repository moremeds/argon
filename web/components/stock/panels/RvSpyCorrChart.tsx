import { toNum } from "@/lib/formatters";
import { finiteDomain, linearScale, pathFromPoints } from "@/lib/svgChart";
import type { Point } from "@/lib/svgChart";
import { AnalyticalSeriesPanel } from "./AnalyticalSeriesPanel";

export type RvCorrPoint = {
  date: string;
  rv: string | number | null;
  spy_corr_21: string | number | null;
};

export function RvSpyCorrChart({ data }: { data: RvCorrPoint[] }) {
  if (data.length < 2) {
    return (
      <AnalyticalSeriesPanel
        title="RV / SPY-corr-1m"
        subtitle="Analytical time series"
      >
        <div style={{ color: "var(--text-muted)", fontSize: 11 }}>
          Insufficient history (need ≥2d)
        </div>
      </AnalyticalSeriesPanel>
    );
  }
  const corrs = data.map((d) => toNum(d.spy_corr_21));
  // Spec §7.4: explicit empty state when SPY hasn't been seeded.
  if (corrs.every((c) => c == null)) {
    return (
      <AnalyticalSeriesPanel
        title="RV / SPY-corr-1m"
        subtitle="Analytical time series"
      >
        <div style={{ color: "var(--text-muted)", fontSize: 11 }}>
          SPY OHLC not seeded — run scripts/seed_spy_ohlc.py
        </div>
      </AnalyticalSeriesPanel>
    );
  }

  const W = 400;
  const H = 220;
  const M = { top: 8, right: 48, bottom: 24, left: 48 };
  const rvs = data.map((d) => toNum(d.rv));
  const rvDomain = finiteDomain(rvs);
  const corrDomain = finiteDomain(corrs);
  if (!rvDomain) {
    return (
      <AnalyticalSeriesPanel
        title="RV / SPY-corr-1m"
        subtitle="Analytical time series"
      >
        <div style={{ color: "var(--text-muted)", fontSize: 11 }}>
          Insufficient finite RV
        </div>
      </AnalyticalSeriesPanel>
    );
  }
  const x = linearScale([0, data.length - 1], [M.left, W - M.right]);
  const yL = linearScale([rvDomain.lo, rvDomain.hi], [H - M.bottom, M.top]);
  const yR = corrDomain
    ? linearScale([corrDomain.lo, corrDomain.hi], [H - M.bottom, M.top])
    : null;
  const rvPath = pathFromPoints(
    rvs
      .map((v, i) => [x(i), v == null ? NaN : yL(v)] as Point)
      .filter(([, y]) => Number.isFinite(y)),
  );
  const corrPath = yR
    ? pathFromPoints(
        corrs
          .map((v, i) => [x(i), v == null ? NaN : yR(v)] as Point)
          .filter(([, y]) => Number.isFinite(y)),
      )
    : "";

  return (
    <AnalyticalSeriesPanel
      title="RV / SPY-corr-1m"
      subtitle="Analytical time series"
    >
      <div style={{ display: "flex", gap: 12, fontSize: 10, marginBottom: 4 }}>
        <span style={{ color: "var(--accent-warm)" }}>— RV (L)</span>
        <span style={{ color: "var(--accent-vivid)" }}>— SPY-corr-21 (R)</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img">
        <path
          d={rvPath}
          stroke="var(--accent-warm)"
          fill="none"
          strokeWidth={1.5}
        />
        <path
          d={corrPath}
          stroke="var(--accent-vivid)"
          fill="none"
          strokeWidth={1.5}
        />
        <text
          x={M.left - 4}
          y={H - M.bottom}
          fontSize={9}
          textAnchor="end"
          fill="var(--accent-warm)"
        >
          {(rvDomain.lo * 100).toFixed(0)}%
        </text>
        <text
          x={M.left - 4}
          y={M.top + 8}
          fontSize={9}
          textAnchor="end"
          fill="var(--accent-warm)"
        >
          {(rvDomain.hi * 100).toFixed(0)}%
        </text>
        {corrDomain && (
          <>
            <text
              x={W - M.right + 4}
              y={H - M.bottom}
              fontSize={9}
              fill="var(--accent-vivid)"
            >
              {corrDomain.lo.toFixed(2)}
            </text>
            <text
              x={W - M.right + 4}
              y={M.top + 8}
              fontSize={9}
              fill="var(--accent-vivid)"
            >
              {corrDomain.hi.toFixed(2)}
            </text>
          </>
        )}
        <text x={M.left} y={H - 4} fontSize={9} fill="var(--text-muted)">
          {data[0].date}
        </text>
        <text
          x={W - M.right}
          y={H - 4}
          fontSize={9}
          textAnchor="end"
          fill="var(--text-muted)"
        >
          {data[data.length - 1].date}
        </text>
      </svg>
    </AnalyticalSeriesPanel>
  );
}
