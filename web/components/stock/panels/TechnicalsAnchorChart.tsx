import type { ReactNode } from "react";
import type { TechnicalsResponse } from "@/lib/api";
import {
  finiteDomain,
  linearScale,
  niceTicks,
  pathFromNullablePoints,
} from "@/lib/svgChart";
import { AnalyticalSeriesPanel } from "./AnalyticalSeriesPanel";
import { ChartDateAxis } from "./ChartDateAxis";
import { CPAD, CW, xScaleFor } from "./OscillatorChart";

const H = 320;

type Row = TechnicalsResponse["series"][number];

export function TechnicalsAnchorChart({
  data,
  control,
}: {
  data: TechnicalsResponse;
  // Optional control (the timeframe selector) rendered next to the date badge.
  control?: ReactNode;
}) {
  // Headline = [control] [as-of date]. Passed to every return path so the
  // selector never vanishes, even on the not-enough-history states.
  const header: ReactNode = (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 10 }}>
      {control}
      <span>{data.as_of ?? ""}</span>
    </span>
  );
  const series = data.series ?? [];
  if (series.length < 2) {
    return (
      <AnalyticalSeriesPanel
        title="Price, Moving Averages & ±1.5σ Band"
        subtitle="anchor"
        headline={header}
      >
        <div style={{ color: "var(--text-muted)", fontSize: 12 }}>
          Not enough history.
        </div>
      </AnalyticalSeriesPanel>
    );
  }

  // ±1.5σ envelope recovered from stored z: half = 1.5 * (close - sma200) / z.
  const upper: Array<number | null> = [];
  const lower: Array<number | null> = [];
  for (const r of series) {
    const c = r.close;
    const m = r.sma200;
    const z = r.z;
    if (c != null && m != null && z != null && z !== 0 && Number.isFinite(z)) {
      const half = 1.5 * ((c - m) / z);
      upper.push(m + half);
      lower.push(m - half);
    } else {
      upper.push(null);
      lower.push(null);
    }
  }

  const closes = series.map((r: Row) => r.close ?? null);
  const s20 = series.map((r: Row) => r.sma20 ?? null);
  const s50 = series.map((r: Row) => r.sma50 ?? null);
  const s200 = series.map((r: Row) => r.sma200 ?? null);

  const dom = finiteDomain([
    ...closes,
    ...s20,
    ...s50,
    ...s200,
    ...upper,
    ...lower,
  ]);
  if (!dom) {
    return (
      <AnalyticalSeriesPanel
        title="Price, Moving Averages & ±1.5σ Band"
        subtitle="anchor"
        headline={header}
      >
        <div style={{ color: "var(--text-muted)", fontSize: 12 }}>
          Not enough finite data.
        </div>
      </AnalyticalSeriesPanel>
    );
  }

  const n = series.length;
  const x = xScaleFor(n); // shared geometry -> columns align with the oscillators
  const y = linearScale([dom.lo, dom.hi], [H - CPAD.b, CPAD.t]);
  const pts = (vals: Array<number | null>) =>
    vals.map((v, i) => (v == null ? null : ([x(i), y(v)] as [number, number])));
  const yTicks = niceTicks(dom.lo, dom.hi, 5);

  // Envelope polygon: upper forward, lower reversed (finite spans only).
  const upFin = upper
    .map((v, i) => (v == null ? null : ([x(i), y(v)] as [number, number])))
    .filter((p): p is [number, number] => p != null);
  const loFin = lower
    .map((v, i) => (v == null ? null : ([x(i), y(v)] as [number, number])))
    .filter((p): p is [number, number] => p != null);
  const envPoly =
    upFin.length > 1 && loFin.length > 1
      ? "M" +
        upFin.map(([px, py]) => `${px},${py}`).join(" L") +
        " L" +
        [...loFin]
          .reverse()
          .map(([px, py]) => `${px},${py}`)
          .join(" L") +
        " Z"
      : null;

  return (
    <AnalyticalSeriesPanel
      title="Price, Moving Averages & ±1.5σ Band"
      subtitle="anchor · aligns with the panels below"
      headline={header}
    >
      <svg
        viewBox={`0 0 ${CW} ${H}`}
        width="100%"
        role="img"
        style={{ display: "block" }}
      >
        <title>Price with SMA20/50/200 and ±1.5σ band around the 200 DMA</title>
        {yTicks.map((t) => (
          <g key={t}>
            <line
              x1={CPAD.l}
              x2={CW - CPAD.r}
              y1={y(t)}
              y2={y(t)}
              stroke="var(--border-dim)"
              strokeWidth={0.4}
              strokeDasharray="2 3"
            />
            <text
              x={CPAD.l - 6}
              y={y(t) + 3}
              fontSize={9}
              fill="var(--text-muted)"
              textAnchor="end"
              fontFamily="var(--font-mono)"
            >
              {t.toFixed(t >= 100 ? 0 : 1)}
            </text>
          </g>
        ))}
        {envPoly && (
          <path
            d={envPoly}
            fill="var(--accent-bg)"
            opacity={0.1}
            stroke="none"
          />
        )}
        <path
          d={pathFromNullablePoints(pts(s200))}
          fill="none"
          stroke="var(--accent-vivid)"
          strokeWidth={1}
          opacity={0.9}
        />
        <path
          d={pathFromNullablePoints(pts(s50))}
          fill="none"
          stroke="var(--accent-vol)"
          strokeWidth={1}
          opacity={0.8}
        />
        <path
          d={pathFromNullablePoints(pts(s20))}
          fill="none"
          stroke="var(--accent-warm)"
          strokeWidth={1}
          opacity={0.8}
        />
        <path
          d={pathFromNullablePoints(pts(closes))}
          fill="none"
          stroke="var(--text-primary)"
          strokeWidth={1.5}
        />
        <ChartDateAxis
          dates={series.map((r: Row) => r.as_of)}
          x={x}
          y={H - 5}
        />
      </svg>
      <Legend />
    </AnalyticalSeriesPanel>
  );
}

function Legend() {
  const item = (color: string, label: string) => (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        marginRight: 12,
      }}
    >
      <span
        style={{
          width: 12,
          height: 2,
          background: color,
          display: "inline-block",
        }}
      />
      <span style={{ fontSize: 10, color: "var(--text-muted)" }}>{label}</span>
    </span>
  );
  return (
    <div style={{ marginTop: 6 }}>
      {item("var(--text-primary)", "CLOSE")}
      {item("var(--accent-warm)", "SMA20")}
      {item("var(--accent-vol)", "SMA50")}
      {item("var(--accent-vivid)", "SMA200")}
    </div>
  );
}
