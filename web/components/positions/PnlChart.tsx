import { finiteDomain, linearScale, pathFromPoints } from "@/lib/svgChart";
import type { Point } from "@/lib/svgChart";

// Pure SVG P&L curve for one VRP-macro cohort: unrealized P&L (option points)
// across its captured marks, with a zero baseline. No chart library.

const W = 520;
const H = 140;
const PAD = { top: 12, right: 12, bottom: 18, left: 40 };

export function PnlChart({ pnl }: { pnl: Array<number | null> }) {
  const dom = finiteDomain(pnl);
  if (dom === null) {
    return (
      <div
        style={{
          color: "var(--text-muted)",
          fontSize: 12,
          fontFamily: "var(--font-mono)",
          padding: "12px 0",
        }}
      >
        Not enough marks to plot a P&L curve yet.
      </div>
    );
  }
  // Always include 0 in the range so the baseline is meaningful.
  const lo = Math.min(dom.lo, 0);
  const hi = Math.max(dom.hi, 0);
  const pad = (hi - lo) * 0.08 || 1;
  const x = linearScale([0, Math.max(1, pnl.length - 1)], [PAD.left, W - PAD.right]);
  const y = linearScale([lo - pad, hi + pad], [H - PAD.bottom, PAD.top]);

  const pts: Point[] = [];
  pnl.forEach((v, i) => {
    if (v != null && Number.isFinite(v)) pts.push([x(i), y(v)]);
  });
  const zeroY = y(0);
  const last = [...pnl].reverse().find((v) => v != null && Number.isFinite(v));
  const lastColor =
    last == null
      ? "var(--text-muted)"
      : last >= 0
        ? "var(--positive)"
        : "var(--negative)";

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      width="100%"
      role="img"
      aria-label="Unrealized P&L across marks"
      style={{ maxWidth: W }}
    >
      <title>Unrealized P&amp;L (option points) across captured marks</title>
      {/* zero baseline */}
      <line
        x1={PAD.left}
        x2={W - PAD.right}
        y1={zeroY}
        y2={zeroY}
        stroke="var(--border)"
        strokeDasharray="3 3"
      />
      <text
        x={PAD.left - 4}
        y={zeroY + 3}
        textAnchor="end"
        fontSize={9}
        fontFamily="var(--font-mono)"
        fill="var(--text-muted)"
      >
        0
      </text>
      <text
        x={PAD.left - 4}
        y={y(hi) + 3}
        textAnchor="end"
        fontSize={9}
        fontFamily="var(--font-mono)"
        fill="var(--text-muted)"
      >
        {hi.toFixed(1)}
      </text>
      <path
        d={pathFromPoints(pts)}
        fill="none"
        stroke={lastColor}
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      {pts.length > 0 && (
        <circle cx={pts[pts.length - 1][0]} cy={pts[pts.length - 1][1]} r={2.5} fill={lastColor} />
      )}
    </svg>
  );
}
