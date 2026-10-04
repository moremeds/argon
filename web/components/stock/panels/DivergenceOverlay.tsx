import { toNum } from "@/lib/formatters";
import { chartFrame, finiteDomain, pathFromPoints } from "@/lib/svgChart";
import type { Point } from "@/lib/svgChart";
import { FrameLabels } from "@/components/shared/FrameLabels";
import { AnalyticalSeriesPanel } from "./AnalyticalSeriesPanel";

export type DivergencePoint = {
  date: string;
  iv_z?: string | number | null | undefined;
  rv_z?: string | number | null | undefined;
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
  const frame = chartFrame();
  const { W, M } = frame;
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
  const x = frame.x([0, data.length - 1]);
  const y = frame.y([domain.lo, domain.hi]);
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
      <svg {...frame.svg}>
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
        <FrameLabels
          frame={frame}
          yLo={<>{domain.lo.toFixed(1)}σ</>}
          yHi={<>{domain.hi.toFixed(1)}σ</>}
          xFirst={data[0].date}
          xLast={data[data.length - 1].date}
        />
      </svg>
    </AnalyticalSeriesPanel>
  );
}
