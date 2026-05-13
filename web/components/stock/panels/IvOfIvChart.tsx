import { toNum } from "@/lib/formatters";
import { finiteDomain, linearScale, pathFromPoints } from "@/lib/svgChart";
import type { Point } from "@/lib/svgChart";
import { AnalyticalSeriesPanel } from "./AnalyticalSeriesPanel";

export type IvOfIvPoint = {
  date: string;
  iv: string | number | null;
  iv_of_iv_20: string | number | null;
};

export function IvOfIvChart({ data }: { data: IvOfIvPoint[] }) {
  if (data.length < 2) {
    return (
      <AnalyticalSeriesPanel
        title="IV / IV-of-IV"
        subtitle="Analytical time series"
      >
        <div style={{ color: "var(--text-muted)", fontSize: 11 }}>
          Insufficient history (need ≥2d)
        </div>
      </AnalyticalSeriesPanel>
    );
  }
  const W = 400;
  const H = 220;
  const M = { top: 8, right: 48, bottom: 24, left: 48 };
  const ivs = data.map((d) => toNum(d.iv));
  const vols = data.map((d) => toNum(d.iv_of_iv_20));
  const ivDomain = finiteDomain(ivs);
  const volDomain = finiteDomain(vols);
  if (!ivDomain) {
    return (
      <AnalyticalSeriesPanel
        title="IV / IV-of-IV"
        subtitle="Analytical time series"
      >
        <div style={{ color: "var(--text-muted)", fontSize: 11 }}>
          Insufficient finite IV
        </div>
      </AnalyticalSeriesPanel>
    );
  }
  const x = linearScale([0, data.length - 1], [M.left, W - M.right]);
  const yL = linearScale([ivDomain.lo, ivDomain.hi], [H - M.bottom, M.top]);
  const yR = volDomain
    ? linearScale([volDomain.lo, volDomain.hi], [H - M.bottom, M.top])
    : null;
  const ivPath = pathFromPoints(
    ivs
      .map((v, i) => [x(i), v == null ? NaN : yL(v)] as Point)
      .filter(([, y]) => Number.isFinite(y)),
  );
  const volPath = yR
    ? pathFromPoints(
        vols
          .map((v, i) => [x(i), v == null ? NaN : yR(v)] as Point)
          .filter(([, y]) => Number.isFinite(y)),
      )
    : "";
  return (
    <AnalyticalSeriesPanel
      title="IV / IV-of-IV"
      subtitle="Analytical time series"
    >
      <div style={{ display: "flex", gap: 12, fontSize: 10, marginBottom: 4 }}>
        <span style={{ color: "var(--accent-bg)" }}>— IV (L)</span>
        <span style={{ color: "var(--accent-vol)" }}>— IV-of-IV (R)</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img">
        <path
          d={ivPath}
          stroke="var(--accent-bg)"
          fill="none"
          strokeWidth={1.5}
        />
        <path
          d={volPath}
          stroke="var(--accent-vol)"
          fill="none"
          strokeWidth={1.5}
        />
        <text
          x={M.left - 4}
          y={H - M.bottom}
          fontSize={9}
          textAnchor="end"
          fill="var(--accent-bg)"
        >
          {(ivDomain.lo * 100).toFixed(0)}%
        </text>
        <text
          x={M.left - 4}
          y={M.top + 8}
          fontSize={9}
          textAnchor="end"
          fill="var(--accent-bg)"
        >
          {(ivDomain.hi * 100).toFixed(0)}%
        </text>
        {volDomain && (
          <>
            <text
              x={W - M.right + 4}
              y={H - M.bottom}
              fontSize={9}
              fill="var(--accent-vol)"
            >
              {(volDomain.lo * 100).toFixed(0)}%
            </text>
            <text
              x={W - M.right + 4}
              y={M.top + 8}
              fontSize={9}
              fill="var(--accent-vol)"
            >
              {(volDomain.hi * 100).toFixed(0)}%
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
