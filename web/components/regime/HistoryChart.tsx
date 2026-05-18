"use client";

import { finiteDomain, linearScale, pathFromPoints } from "@/lib/svgChart";
import type { GexHistoryEntry } from "@/lib/regime/useGex";

const WIDTH = 760;
const HEIGHT = 220;
const PAD = { top: 12, right: 56, bottom: 28, left: 56 };

export function HistoryChart({
  history,
  ticker,
}: {
  history: GexHistoryEntry[];
  ticker: string;
}) {
  if (!history.length) {
    return (
      <div
        style={{
          padding: "24px",
          color: "var(--text-muted)",
          fontFamily: "var(--font-mono)",
          fontSize: 11,
          letterSpacing: "0.06em",
          textTransform: "uppercase",
        }}
      >
        No history available
      </div>
    );
  }

  const xScale = linearScale(
    [0, Math.max(history.length - 1, 1)],
    [PAD.left, WIDTH - PAD.right],
  );

  // finiteDomain returns {lo, hi, count} | null — null on <2 finite values
  const netGexD = finiteDomain(history.map((h) => h.net_gex));
  const priceD = finiteDomain(history.flatMap((h) => [h.spot, h.gex_flip]));

  const yGex = netGexD
    ? linearScale([netGexD.lo, netGexD.hi], [HEIGHT - PAD.bottom, PAD.top])
    : null;
  const yPrice = priceD
    ? linearScale([priceD.lo, priceD.hi], [HEIGHT - PAD.bottom, PAD.top])
    : null;

  const netGexPath =
    yGex == null
      ? ""
      : pathFromPoints(
          history
            .map((h, i): [number, number] | null =>
              h.net_gex == null ? null : [xScale(i), yGex(h.net_gex)],
            )
            .filter((p): p is [number, number] => p != null),
        );

  const flipPath =
    yPrice == null
      ? ""
      : pathFromPoints(
          history
            .map((h, i): [number, number] | null =>
              h.gex_flip == null ? null : [xScale(i), yPrice(h.gex_flip)],
            )
            .filter((p): p is [number, number] => p != null),
        );

  const spotPath =
    yPrice == null
      ? ""
      : pathFromPoints(
          history
            .map((h, i): [number, number] | null =>
              h.spot == null ? null : [xScale(i), yPrice(h.spot)],
            )
            .filter((p): p is [number, number] => p != null),
        );

  return (
    <svg
      role="img"
      aria-label={`${ticker} 90-day GEX history`}
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      style={{ width: "100%", height: HEIGHT, display: "block" }}
    >
      <title>{`${ticker} — net GEX, flip migration, spot`}</title>

      {/* zero line for net GEX (only when scale exists and crosses zero) */}
      {yGex != null &&
        netGexD != null &&
        netGexD.lo <= 0 &&
        netGexD.hi >= 0 && (
          <line
            x1={PAD.left}
            x2={WIDTH - PAD.right}
            y1={yGex(0)}
            y2={yGex(0)}
            stroke="var(--border-dim)"
            strokeDasharray="2 3"
          />
        )}

      {/* net_gex (left axis) */}
      <path
        d={netGexPath}
        fill="none"
        stroke="var(--accent-bg)"
        strokeWidth={1.5}
      />

      {/* gex_flip (right axis) — sparse / forward-only */}
      <path
        d={flipPath}
        fill="none"
        stroke="var(--accent-warm)"
        strokeWidth={1.2}
        strokeDasharray="3 2"
      />

      {/* spot (right axis) */}
      <path
        d={spotPath}
        fill="none"
        stroke="var(--text-primary)"
        strokeWidth={1.2}
      />
    </svg>
  );
}
