"use client";

import {
  finiteDomain,
  linearScale,
  pathFromNullablePoints,
} from "@/lib/svgChart";

const W = 200;
const H = 30;

/**
 * Width-filling sparkline for regime cards/tiles. The viewBox is stretched
 * (`preserveAspectRatio="none"`) so the line always fills the card width at a
 * fixed pixel height; `vector-effect: non-scaling-stroke` keeps the stroke
 * crisp under the non-uniform scale.
 */
export default function CardSparkline({
  values,
  label,
  color = "var(--accent-bg, #05AD98)",
  height = 28,
}: {
  values: ReadonlyArray<number | null | undefined>;
  label: string;
  color?: string;
  height?: number;
}) {
  const domain = finiteDomain(values);
  if (!domain) return null;
  const x = linearScale([0, Math.max(values.length - 1, 1)], [1, W - 1]);
  const y = linearScale([domain.lo, domain.hi], [H - 2, 2]);
  const d = pathFromNullablePoints(
    values.map((v, i): [number, number] | null =>
      v == null || !Number.isFinite(v) ? null : [x(i), y(v)],
    ),
  );
  return (
    <svg
      role="img"
      aria-label={label}
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      style={{
        width: "100%",
        height,
        display: "block",
        marginTop: 6,
        opacity: 0.9,
      }}
    >
      <path
        d={d}
        fill="none"
        stroke={color}
        strokeWidth={1.2}
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}
