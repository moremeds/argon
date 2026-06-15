"use client";

import { fmtSigned, toNum } from "@/lib/formatters";
import { finiteDomain, linearScale, pathFromPoints } from "@/lib/svgChart";
import type { Point } from "@/lib/svgChart";

import { AnalyticalSeriesPanel } from "./AnalyticalSeriesPanel";

type RhoPt = { date: string; rho?: string | number | null };

export function SkewRhoPanel({
  rho63,
  rho21,
  series = [],
}: {
  rho63?: string | number | null;
  rho21?: string | number | null;
  series?: RhoPt[];
}) {
  const r63 = toNum(rho63);
  const r21 = toNum(rho21);
  const color = (v: number | null) =>
    v == null
      ? "var(--text-muted)"
      : v < 0
        ? "var(--negative)"
        : "var(--positive)";
  const vals = series
    .map((p) => toNum(p.rho))
    .filter((v): v is number => v != null);
  const dom = finiteDomain(vals.length ? [...vals, -1, 1] : []);
  let spark = null;
  if (dom && series.length >= 2) {
    const W = 320;
    const H = 56;
    const x = linearScale([0, series.length - 1], [2, W - 2]);
    const y = linearScale([dom.lo, dom.hi], [H - 4, 4]);
    const pts: Point[] = series
      .map((p, i): Point | null => {
        const v = toNum(p.rho);
        return v == null ? null : [x(i), y(v)];
      })
      .filter((p): p is Point => p != null);
    spark = (
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img">
        <title>Spot-vol ρ (63d) over time</title>
        <line
          x1={2}
          x2={W - 2}
          y1={y(0)}
          y2={y(0)}
          stroke="var(--border-dim)"
        />
        <path d={pathFromPoints(pts)} fill="none" stroke="var(--accent-vol)" />
      </svg>
    );
  }
  return (
    <AnalyticalSeriesPanel title="Spot-Vol ρ" subtitle="PANIC vs CHASE">
      <div style={{ display: "flex", gap: 24 }}>
        <div>
          <div style={{ fontSize: 10, color: "var(--text-muted)" }}>63d</div>
          <div style={{ fontSize: 22, fontWeight: 700, color: color(r63) }}>
            {r63 != null ? fmtSigned(r63, 2) : "—"}
          </div>
        </div>
        <div>
          <div style={{ fontSize: 10, color: "var(--text-muted)" }}>21d</div>
          <div style={{ fontSize: 22, fontWeight: 700, color: color(r21) }}>
            {r21 != null ? fmtSigned(r21, 2) : "—"}
          </div>
        </div>
      </div>
      {spark}
      <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 8 }}>
        ρ&lt;0 → vol rises as spot falls (hedging fear). ρ&gt;0 → chase.
      </div>
    </AnalyticalSeriesPanel>
  );
}
