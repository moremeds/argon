import { toNum } from "@/lib/formatters";
import { finiteDomain, linearScale, pathFromPoints } from "@/lib/svgChart";
import type { Point } from "@/lib/svgChart";
import { AnalyticalSeriesPanel } from "./AnalyticalSeriesPanel";

export type SmilePoint = {
  strike: string | number;
  iv?: string | number | null | undefined;
};

export type SmileExpiryCurve = {
  expiry: string;
  points: SmilePoint[];
};

const COLORS = [
  "var(--accent-bg)",
  "var(--accent-warm)",
  "var(--accent-vol)",
  "var(--accent-vivid)",
];

export function SmileChart({ data }: { data: SmileExpiryCurve[] }) {
  if (data.length === 0) {
    return (
      <AnalyticalSeriesPanel title="Smile" subtitle="IV by strike">
        <div style={{ color: "var(--text-muted)", fontSize: 11 }}>
          No smile data
        </div>
      </AnalyticalSeriesPanel>
    );
  }

  const allStrikes: number[] = [];
  const allIvs: number[] = [];
  for (const curve of data) {
    for (const p of curve.points) {
      const s = toNum(p.strike);
      const v = toNum(p.iv);
      if (s != null) allStrikes.push(s);
      if (v != null) allIvs.push(v);
    }
  }
  const strikeDomain = finiteDomain(allStrikes);
  const ivDomain = finiteDomain(allIvs);
  if (!strikeDomain || !ivDomain) {
    return (
      <AnalyticalSeriesPanel title="Smile" subtitle="IV by strike">
        <div style={{ color: "var(--text-muted)", fontSize: 11 }}>
          Insufficient finite smile data
        </div>
      </AnalyticalSeriesPanel>
    );
  }
  const W = 400;
  const H = 220;
  const M = { top: 8, right: 16, bottom: 24, left: 36 };
  const x = linearScale(
    [strikeDomain.lo, strikeDomain.hi],
    [M.left, W - M.right],
  );
  const y = linearScale([ivDomain.lo, ivDomain.hi], [H - M.bottom, M.top]);

  return (
    <AnalyticalSeriesPanel title="Smile" subtitle="IV by strike">
      <div style={{ display: "flex", gap: 12, fontSize: 10, marginBottom: 4 }}>
        {data.slice(0, COLORS.length).map((c, i) => (
          <span key={c.expiry} style={{ color: COLORS[i] }}>
            — {c.expiry}
          </span>
        ))}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img">
        {data.slice(0, COLORS.length).map((curve, i) => {
          const pts: Point[] = curve.points
            .map((p) => {
              const s = toNum(p.strike);
              const v = toNum(p.iv);
              return s != null && v != null ? ([x(s), y(v)] as Point) : null;
            })
            .filter((p): p is Point => p !== null);
          return (
            <path
              key={curve.expiry}
              d={pathFromPoints(pts)}
              stroke={COLORS[i]}
              fill="none"
              strokeWidth={1.5}
            />
          );
        })}
        <text
          x={M.left - 4}
          y={H - M.bottom}
          fontSize={9}
          textAnchor="end"
          fill="var(--text-muted)"
        >
          {(ivDomain.lo * 100).toFixed(1)}%
        </text>
        <text
          x={M.left - 4}
          y={M.top + 8}
          fontSize={9}
          textAnchor="end"
          fill="var(--text-muted)"
        >
          {(ivDomain.hi * 100).toFixed(1)}%
        </text>
        <text x={M.left} y={H - 4} fontSize={9} fill="var(--text-muted)">
          ${strikeDomain.lo.toFixed(0)}
        </text>
        <text
          x={W - M.right}
          y={H - 4}
          fontSize={9}
          textAnchor="end"
          fill="var(--text-muted)"
        >
          ${strikeDomain.hi.toFixed(0)}
        </text>
      </svg>
    </AnalyticalSeriesPanel>
  );
}
