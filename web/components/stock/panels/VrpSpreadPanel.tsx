import { toNum } from "@/lib/formatters";
import { finiteDomain, linearScale, pathFromPoints } from "@/lib/svgChart";
import type { Point } from "@/lib/svgChart";
import { AnalyticalSeriesPanel } from "./AnalyticalSeriesPanel";

export type VrpDailyPoint = {
  date: string;
  vrp?: string | number | null | undefined;
  vrp_z_20?: string | number | null | undefined;
};

export function VrpSpreadPanel({
  data,
  headline,
}: {
  data: VrpDailyPoint[];
  headline?: string;
}) {
  if (data.length === 0) {
    return (
      <AnalyticalSeriesPanel
        title="VRP Spread"
        subtitle="30-session bars + line"
        headline={headline}
      >
        <div style={{ color: "var(--text-muted)", fontSize: 11 }}>
          No VRP history
        </div>
      </AnalyticalSeriesPanel>
    );
  }
  const W = 800;
  const H = 220;
  const M = { top: 8, right: 24, bottom: 24, left: 48 };
  const innerW = W - M.left - M.right;
  const barCount = data.length;
  const barW = innerW / barCount;
  const vrps = data.map((d) => toNum(d.vrp));
  const zs = data.map((d) => toNum(d.vrp_z_20));
  const vrpDomain = finiteDomain(vrps);
  const zDomain = finiteDomain(zs);
  if (!vrpDomain) {
    return (
      <AnalyticalSeriesPanel
        title="VRP Spread"
        subtitle="30-session bars + line"
        headline={headline}
      >
        <div style={{ color: "var(--text-muted)", fontSize: 11 }}>
          Insufficient finite VRP
        </div>
      </AnalyticalSeriesPanel>
    );
  }
  // Symmetric Y around 0 so positive/negative bars line up.
  const maxAbs = Math.max(Math.abs(vrpDomain.lo), Math.abs(vrpDomain.hi)) || 1;
  const yBar = linearScale([-maxAbs, maxAbs], [H - M.bottom, M.top]);
  const yLine = zDomain
    ? linearScale([zDomain.lo, zDomain.hi], [H - M.bottom, M.top])
    : null;
  const zPath = yLine
    ? pathFromPoints(
        zs
          .map(
            (v, i) =>
              [
                M.left + i * barW + barW / 2,
                v == null ? NaN : yLine(v),
              ] as Point,
          )
          .filter(([, y]) => Number.isFinite(y)),
      )
    : "";

  return (
    <AnalyticalSeriesPanel
      title="VRP Spread"
      subtitle="30-session bars + smoothed z-overlay"
      headline={headline}
    >
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img">
        <line
          x1={M.left}
          x2={W - M.right}
          y1={yBar(0)}
          y2={yBar(0)}
          stroke="var(--chart-grid)"
        />
        {vrps.map((v, i) => {
          if (v == null) return null;
          const yTop = yBar(Math.max(0, v));
          const yBot = yBar(Math.min(0, v));
          return (
            <rect
              key={i}
              x={M.left + i * barW + 1}
              y={yTop}
              width={Math.max(1, barW - 2)}
              height={Math.max(1, yBot - yTop)}
              fill={v >= 0 ? "var(--positive)" : "var(--negative)"}
              opacity={0.7}
            />
          );
        })}
        <path d={zPath} stroke="var(--accent-bg)" fill="none" strokeWidth={2} />
        <text
          x={M.left - 4}
          y={M.top + 8}
          fontSize={9}
          textAnchor="end"
          fill="var(--text-muted)"
        >
          +{maxAbs.toFixed(2)}
        </text>
        <text
          x={M.left - 4}
          y={H - M.bottom}
          fontSize={9}
          textAnchor="end"
          fill="var(--text-muted)"
        >
          -{maxAbs.toFixed(2)}
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
