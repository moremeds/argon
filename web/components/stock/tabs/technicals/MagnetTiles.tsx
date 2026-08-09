"use client";

import type { ReactNode } from "react";

import { isNum, tileDomain, type Num } from "@/lib/magnetTiles";
import { linearScale, pathFromPoints, type Point } from "@/lib/svgChart";

/**
 * The four KPI tiles under the magnet chart. Each is a headline plus its own
 * mini-chart, drawn in the chart type the underlying series actually is —
 * volume is bars, RSI is a bounded oscillator with regime zones, momentum is a
 * signed area straddling zero, IV is a level. Reference spec §5.1 item 3.
 *
 * Hand-rolled SVG per the house rule (web/CLAUDE.md): the two lightweight-charts
 * exceptions are the price pane and the density cone. All four charts share one
 * `viewBox="0 0 100 H"` + `preserveAspectRatio="none"` frame so they stretch to
 * the tile; every stroke carries `vectorEffect="non-scaling-stroke"` so that
 * stretch does not also stretch the line weight.
 */

const H = 46; // chart height inside a tile
const PAD = 3;

function Frame({ children, label }: { children: ReactNode; label: string }) {
  return (
    <svg
      viewBox={`0 0 100 ${H}`}
      width="100%"
      height={H}
      preserveAspectRatio="none"
      role="img"
      aria-label={label}
      style={{ display: "block", marginTop: 6 }}
    >
      {children}
    </svg>
  );
}

/** Volume bars coloured by that session's own direction, over a dashed MA. */
export function VolumeChart({
  bars,
  ma,
}: {
  bars: { volume: Num; up: boolean }[];
  ma: Num[];
}) {
  const dom = tileDomain([...bars.map((b) => b.volume), ...ma], {
    includeZero: true,
  });
  if (!dom) return null;
  const x = linearScale([0, Math.max(bars.length - 1, 1)], [PAD, 100 - PAD]);
  const y = linearScale([dom.lo, dom.hi], [H - PAD, PAD]);
  const w = Math.max((100 - PAD * 2) / Math.max(bars.length, 1) - 0.6, 0.6);
  const maPts: Point[] = [];
  ma.forEach((v, i) => isNum(v) && maPts.push([x(i), y(v)]));

  return (
    <Frame label={`${bars.length}-session volume`}>
      {bars.map((b, i) =>
        isNum(b.volume) ? (
          <rect
            key={i}
            x={x(i) - w / 2}
            y={y(b.volume)}
            width={w}
            height={Math.max(y(0) - y(b.volume), 0.5)}
            fill={b.up ? "var(--positive)" : "var(--negative)"}
            opacity={0.75}
          />
        ) : null,
      )}
      {maPts.length > 1 && (
        <path
          d={pathFromPoints(maPts)}
          fill="none"
          stroke="var(--accent-warm)"
          strokeWidth={1}
          strokeDasharray="3 2"
          vectorEffect="non-scaling-stroke"
        />
      )}
    </Frame>
  );
}

/**
 * RSI with its regime zones. The zones are the point: 42 means nothing until
 * you can see it is neither of the two places RSI is read for.
 */
export function RsiChart({ values }: { values: Num[] }) {
  const pts: Point[] = [];
  const x = linearScale([0, Math.max(values.length - 1, 1)], [PAD, 100 - PAD]);
  // Fixed 0–100 domain, NOT the data's own range: RSI is bounded by
  // construction, and autoscaling it would move the 30/70 lines per ticker and
  // make two tiles uncomparable.
  const y = linearScale([0, 100], [H - PAD, PAD]);
  values.forEach((v, i) => isNum(v) && pts.push([x(i), y(v)]));
  if (pts.length < 2) return null;
  const last = pts[pts.length - 1]!;

  return (
    <Frame label={`${values.length}-session RSI 14`}>
      <rect
        x={0}
        y={y(100)}
        width={100}
        height={y(70) - y(100)}
        fill="var(--negative)"
        opacity={0.13}
      />
      <rect
        x={0}
        y={y(30)}
        width={100}
        height={y(0) - y(30)}
        fill="var(--positive)"
        opacity={0.13}
      />
      <path
        d={pathFromPoints(pts)}
        fill="none"
        stroke="var(--accent-vivid)"
        strokeWidth={1.25}
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
      <circle
        cx={last[0]}
        cy={last[1]}
        r={2}
        fill="var(--accent-vivid)"
        vectorEffect="non-scaling-stroke"
      />
    </Frame>
  );
}

/**
 * Signed momentum: area to the zero line, green above / red below, with the
 * slow (55/89/34) histogram dashed behind it. Two series, because the fast one
 * alone cannot distinguish "turning up inside a downtrend" from "turning up".
 */
export function MomentumChart({ fast, slow }: { fast: Num[]; slow: Num[] }) {
  const dom = tileDomain([...fast, ...slow], { includeZero: true });
  if (!dom) return null;
  const x = linearScale([0, Math.max(fast.length - 1, 1)], [PAD, 100 - PAD]);
  const y = linearScale([dom.lo, dom.hi], [H - PAD, PAD]);
  const zero = y(0);

  const pts: Point[] = [];
  fast.forEach((v, i) => isNum(v) && pts.push([x(i), y(v)]));
  if (pts.length < 2) return null;
  const slowPts: Point[] = [];
  slow.forEach((v, i) => isNum(v) && slowPts.push([x(i), y(v)]));

  // One polygon closed onto the zero line, clipped twice — above and below —
  // so a single path can carry both colours without hand-splitting the series
  // at every zero crossing.
  const area = `${pathFromPoints(pts)} L${pts[pts.length - 1]![0]},${zero} L${pts[0]![0]},${zero} Z`;
  const uid = `mom-${fast.length}`;

  return (
    <Frame label={`${fast.length}-session momentum`}>
      <defs>
        <clipPath id={`${uid}-up`}>
          <rect x={0} y={0} width={100} height={Math.max(zero, 0)} />
        </clipPath>
        <clipPath id={`${uid}-dn`}>
          <rect x={0} y={zero} width={100} height={Math.max(H - zero, 0)} />
        </clipPath>
      </defs>
      <path
        d={area}
        fill="var(--positive)"
        opacity={0.4}
        clipPath={`url(#${uid}-up)`}
      />
      <path
        d={area}
        fill="var(--negative)"
        opacity={0.4}
        clipPath={`url(#${uid}-dn)`}
      />
      <line
        x1={0}
        x2={100}
        y1={zero}
        y2={zero}
        stroke="var(--border-dim)"
        strokeWidth={1}
        vectorEffect="non-scaling-stroke"
      />
      {slowPts.length > 1 && (
        <path
          d={pathFromPoints(slowPts)}
          fill="none"
          stroke="var(--accent-warm)"
          strokeWidth={1}
          strokeDasharray="3 2"
          vectorEffect="non-scaling-stroke"
        />
      )}
      <path
        d={pathFromPoints(pts)}
        fill="none"
        stroke="var(--text-primary)"
        strokeWidth={1.1}
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
    </Frame>
  );
}

/** ATM IV as a filled level chart. */
export function IvChart({ values }: { values: number[] }) {
  const dom = tileDomain(values);
  if (!dom) return null;
  const x = linearScale([0, Math.max(values.length - 1, 1)], [PAD, 100 - PAD]);
  const y = linearScale([dom.lo, dom.hi], [H - PAD, PAD]);
  const pts: Point[] = values.map((v, i) => [x(i), y(v)]);
  const last = pts[pts.length - 1]!;
  const area = `${pathFromPoints(pts)} L${last[0]},${H} L${pts[0]![0]},${H} Z`;

  return (
    <Frame label={`${values.length}-session ATM 30d IV`}>
      <path d={area} fill="var(--accent-vol)" opacity={0.22} />
      <path
        d={pathFromPoints(pts)}
        fill="none"
        stroke="var(--accent-vol)"
        strokeWidth={1.25}
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
      <circle cx={last[0]} cy={last[1]} r={2} fill="var(--accent-vol)" />
    </Frame>
  );
}
