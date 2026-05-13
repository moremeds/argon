import { toNum } from "@/lib/formatters";
import { finiteDomain, linearScale, pathFromPoints } from "@/lib/svgChart";
import type { Point } from "@/lib/svgChart";
import { AnalyticalSeriesPanel } from "./AnalyticalSeriesPanel";

export type HvIvPoint = {
  date: string;
  iv: string | number | null;
  rv: string | number | null;
};

export function HvIvChart({ data }: { data: HvIvPoint[] }) {
  if (data.length < 2) {
    return (
      <AnalyticalSeriesPanel title="HV / IV" subtitle="Daily, last ~1y">
        <div style={{ color: "var(--text-muted)", fontSize: 11 }}>
          Insufficient history (need ≥2d, have {data.length}d)
        </div>
      </AnalyticalSeriesPanel>
    );
  }
  const W = 400;
  const H = 220;
  const M = { top: 8, right: 16, bottom: 24, left: 36 };
  const ivs = data.map((d) => toNum(d.iv));
  const rvs = data.map((d) => toNum(d.rv));
  const domain = finiteDomain([...ivs, ...rvs]);
  if (!domain) {
    return (
      <AnalyticalSeriesPanel title="HV / IV" subtitle="Daily, last ~1y">
        <div style={{ color: "var(--text-muted)", fontSize: 11 }}>
          Insufficient finite history
        </div>
      </AnalyticalSeriesPanel>
    );
  }
  const { lo, hi } = domain;
  const x = linearScale([0, data.length - 1], [M.left, W - M.right]);
  const y = linearScale([lo, hi], [H - M.bottom, M.top]);
  const ivPath = pathFromPoints(
    ivs
      .map((v, i) => [x(i), v == null ? NaN : y(v)] as Point)
      .filter(([, vy]) => Number.isFinite(vy)),
  );
  const rvPath = pathFromPoints(
    rvs
      .map((v, i) => [x(i), v == null ? NaN : y(v)] as Point)
      .filter(([, vy]) => Number.isFinite(vy)),
  );
  return (
    <AnalyticalSeriesPanel title="HV / IV" subtitle="Daily, last ~1y">
      <div style={{ display: "flex", gap: 12, fontSize: 10, marginBottom: 4 }}>
        <span style={{ color: "var(--accent-bg)" }}>— IV</span>
        <span style={{ color: "var(--accent-warm)" }}>— RV</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img">
        <path
          d={ivPath}
          stroke="var(--accent-bg)"
          fill="none"
          strokeWidth={1.5}
        />
        <path
          d={rvPath}
          stroke="var(--accent-warm)"
          fill="none"
          strokeWidth={1.5}
        />
        <text
          x={M.left - 4}
          y={H - M.bottom}
          fontSize={9}
          textAnchor="end"
          fill="var(--text-muted)"
        >
          {(lo * 100).toFixed(1)}%
        </text>
        <text
          x={M.left - 4}
          y={M.top + 8}
          fontSize={9}
          textAnchor="end"
          fill="var(--text-muted)"
        >
          {(hi * 100).toFixed(1)}%
        </text>
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
