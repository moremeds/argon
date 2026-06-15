"use client";

import { toNum } from "@/lib/formatters";
import { finiteDomain, linearScale, pathFromPoints } from "@/lib/svgChart";
import type { Point } from "@/lib/svgChart";

import { AnalyticalSeriesPanel } from "./AnalyticalSeriesPanel";

type Pt = {
  date: string;
  rr?: string | number | null;
  pct?: string | number | null;
};

export function SkewHistoryChart({ data }: { data: Pt[] }) {
  const vals = data
    .map((d) => toNum(d.rr))
    .filter((v): v is number => v != null);
  const dom = finiteDomain(vals);
  const curPct = data.length ? toNum(data[data.length - 1].pct) : null;
  const headline = curPct != null ? `${Math.round(curPct)}th pct` : undefined;
  if (!dom || data.length < 2) {
    return (
      <AnalyticalSeriesPanel title="Skew History" subtitle="RR vs TIME">
        <div style={{ color: "var(--text-muted)", fontSize: 11 }}>
          Insufficient skew history
        </div>
      </AnalyticalSeriesPanel>
    );
  }
  const W = 400;
  const H = 200;
  const M = { top: 8, right: 12, bottom: 20, left: 36 };
  const x = linearScale([0, data.length - 1], [M.left, W - M.right]);
  const y = linearScale([dom.lo, dom.hi], [H - M.bottom, M.top]);
  const pts: Point[] = data
    .map((d, i): Point | null => {
      const v = toNum(d.rr);
      return v == null ? null : [x(i), y(v)];
    })
    .filter((p): p is Point => p != null);
  const last = pts[pts.length - 1];
  return (
    <AnalyticalSeriesPanel
      title="Skew History"
      subtitle="RR vs TIME"
      headline={headline}
    >
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img">
        <title>Risk-reversal skew over time with current marker</title>
        <line
          x1={M.left}
          x2={W - M.right}
          y1={y(0)}
          y2={y(0)}
          stroke="var(--border-dim)"
        />
        <path d={pathFromPoints(pts)} fill="none" stroke="var(--accent-bg)" />
        {last ? (
          <circle cx={last[0]} cy={last[1]} r={3} fill="var(--accent-vivid)" />
        ) : null}
      </svg>
    </AnalyticalSeriesPanel>
  );
}
