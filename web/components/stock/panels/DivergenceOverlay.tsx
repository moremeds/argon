import { toNum } from "@/lib/formatters";
import { finiteDomain, linearScale, pathFromPoints } from "@/lib/svgChart";
import type { Point } from "@/lib/svgChart";
import { AnalyticalSeriesPanel } from "./AnalyticalSeriesPanel";

export type DivergencePoint = {
  date: string;
  iv_z: string | number | null;
  rv_z: string | number | null;
};

export function DivergenceOverlay({
  data,
  headline,
}: {
  data: DivergencePoint[];
  headline?: string;
}) {
  if (data.length < 2) {
    return (
      <AnalyticalSeriesPanel
        title="IV-z vs RV-z"
        subtitle="20-session overlay"
        headline={headline}
      >
        <div style={{ color: "var(--text-muted)", fontSize: 11 }}>
          Insufficient history (need ≥2d)
        </div>
      </AnalyticalSeriesPanel>
    );
  }
  const W = 400;
  const H = 220;
  const M = { top: 8, right: 16, bottom: 24, left: 36 };
  const ivZ = data.map((d) => toNum(d.iv_z));
  const rvZ = data.map((d) => toNum(d.rv_z));
  const domain = finiteDomain([...ivZ, ...rvZ]);
  if (!domain) {
    return (
      <AnalyticalSeriesPanel
        title="IV-z vs RV-z"
        subtitle="20-session overlay"
        headline={headline}
      >
        <div style={{ color: "var(--text-muted)", fontSize: 11 }}>
          Insufficient finite z-scores
        </div>
      </AnalyticalSeriesPanel>
    );
  }
  const x = linearScale([0, data.length - 1], [M.left, W - M.right]);
  const y = linearScale([domain.lo, domain.hi], [H - M.bottom, M.top]);
  const ivPath = pathFromPoints(
    ivZ
      .map((v, i) => [x(i), v == null ? NaN : y(v)] as Point)
      .filter(([, vy]) => Number.isFinite(vy)),
  );
  const rvPath = pathFromPoints(
    rvZ
      .map((v, i) => [x(i), v == null ? NaN : y(v)] as Point)
      .filter(([, vy]) => Number.isFinite(vy)),
  );
  return (
    <AnalyticalSeriesPanel
      title="IV-z vs RV-z"
      subtitle="20-session overlay"
      headline={headline}
    >
      <div style={{ display: "flex", gap: 12, fontSize: 10, marginBottom: 4 }}>
        <span style={{ color: "var(--accent-warm)" }}>— IV-z</span>
        <span style={{ color: "var(--accent-vivid)" }}>— RV-z</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img">
        {domain.lo < 0 && domain.hi > 0 && (
          <line
            x1={M.left}
            x2={W - M.right}
            y1={y(0)}
            y2={y(0)}
            stroke="var(--chart-grid)"
            strokeDasharray="2,3"
          />
        )}
        <path
          d={ivPath}
          stroke="var(--accent-warm)"
          fill="none"
          strokeWidth={1.5}
        />
        <path
          d={rvPath}
          stroke="var(--accent-vivid)"
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
          {domain.lo.toFixed(1)}σ
        </text>
        <text
          x={M.left - 4}
          y={M.top + 8}
          fontSize={9}
          textAnchor="end"
          fill="var(--text-muted)"
        >
          {domain.hi.toFixed(1)}σ
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
