import type { TechnicalsResponse } from "@/lib/api";
import {
  finiteDomain,
  linearScale,
  pathFromNullablePoints,
} from "@/lib/svgChart";
import { AnalyticalSeriesPanel } from "./AnalyticalSeriesPanel";
import { ChartDateAxis } from "./ChartDateAxis";

const W = 760;
const H = 236;
const PAD = { l: 28, r: 8, t: 8, b: 22 };

export function TechnicalsZChart({ data }: { data: TechnicalsResponse }) {
  const series = data.series ?? [];
  const zs = series.map((r) => r.z ?? null);
  const dom = finiteDomain(zs);
  if (!dom) {
    return (
      <AnalyticalSeriesPanel
        title="Z-Score vs 200 DMA"
        subtitle="σ from the mean"
      >
        <div style={{ color: "var(--text-muted)", fontSize: 12 }}>
          Not enough history for a z-series.
        </div>
      </AnalyticalSeriesPanel>
    );
  }
  const lo = Math.min(dom.lo, -2.5);
  const hi = Math.max(dom.hi, 2.5);
  const n = series.length;
  const x = linearScale([0, Math.max(1, n - 1)], [PAD.l, W - PAD.r]);
  const y = linearScale([lo, hi], [H - PAD.b, PAD.t]);
  const pts = zs.map((v, i) =>
    v == null ? null : ([x(i), y(v)] as [number, number]),
  );

  const refLines = [0, 1, -1, 2, -2];
  const band = (a: number, b: number, color: string) => (
    <rect
      x={PAD.l}
      y={y(b)}
      width={W - PAD.r - PAD.l}
      height={Math.abs(y(a) - y(b))}
      fill={color}
      opacity={0.06}
    />
  );

  return (
    <AnalyticalSeriesPanel
      title="Z-Score vs 200 DMA"
      subtitle="σ from the mean"
      headline={data.header?.z_band ?? undefined}
    >
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        role="img"
        style={{ display: "block" }}
      >
        <title>Z-score of price distance from the 200 DMA over time</title>
        {band(1.5, hi, "var(--negative)")}
        {band(lo, -1.5, "var(--positive)")}
        {refLines.map((rv) => (
          <g key={rv}>
            <line
              x1={PAD.l}
              x2={W - PAD.r}
              y1={y(rv)}
              y2={y(rv)}
              stroke="var(--border-dim)"
              strokeWidth={rv === 0 ? 1 : 0.5}
              strokeDasharray={rv === 0 ? undefined : "3 3"}
            />
            <text
              x={2}
              y={y(rv) + 3}
              fontSize={9}
              fill="var(--text-muted)"
              fontFamily="var(--font-mono)"
            >
              {rv > 0 ? `+${rv}` : rv}σ
            </text>
          </g>
        ))}
        <path
          d={pathFromNullablePoints(pts)}
          fill="none"
          stroke="var(--accent-vivid)"
          strokeWidth={1.5}
        />
        <ChartDateAxis dates={series.map((r) => r.as_of)} x={x} y={H - 5} />
      </svg>
    </AnalyticalSeriesPanel>
  );
}
