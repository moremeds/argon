import {
  finiteDomain,
  linearScale,
  niceTicks,
  pathFromPoints,
  type Point,
} from "@/lib/svgChart";
import { fmtMoneyAbbrev } from "@/lib/formatters";

export type NetExposurePoint = {
  strike: number;
  netValue: number | null;
};

type Props = {
  curve: NetExposurePoint[];
  spot: number | null;
  flipStrike: number | null;
  yLabel: "Vanna" | "Charm";
  title: string;
  width?: number;
  height?: number;
};

const PAD = { top: 36, right: 24, bottom: 40, left: 64 };
const NET_COLOR = "var(--accent-vol)";
const SPOT_COLOR = "var(--warning)";

export function NetExposureChart({
  curve,
  spot,
  flipStrike,
  yLabel,
  title,
  width = 560,
  height = 360,
}: Props) {
  const finitePts = curve.filter(
    (c) =>
      Number.isFinite(c.strike) &&
      c.netValue != null &&
      Number.isFinite(c.netValue as number),
  );

  const panel: React.CSSProperties = {
    background: "var(--bg-panel)",
    border: "1px solid var(--border-dim)",
    borderRadius: 4,
    padding: 16,
    fontFamily: "var(--font-mono)",
  };

  if (finitePts.length === 0) {
    return (
      <div style={panel}>
        <div
          style={{
            fontSize: 13,
            color: "var(--text-secondary)",
            marginBottom: 8,
          }}
        >
          {title}
        </div>
        <div style={{ color: "var(--text-muted)", fontSize: 12 }}>
          Not enough data to render the curve.
        </div>
      </div>
    );
  }

  const xDomain =
    finitePts.length >= 2
      ? finiteDomain(finitePts.map((c) => c.strike))!
      : (() => {
          const s = finitePts[0].strike;
          const half = spot != null ? Math.abs(s - spot) || s * 0.05 : s * 0.05;
          return { lo: s - half, hi: s + half, count: 1 };
        })();
  const yDomain =
    finitePts.length >= 2
      ? finiteDomain(finitePts.map((c) => c.netValue))!
      : (() => {
          const v = Math.abs(finitePts[0].netValue as number);
          return { lo: -v, hi: v, count: 1 };
        })();

  const innerW = width - PAD.left - PAD.right;
  const innerH = height - PAD.top - PAD.bottom;

  const xScale = linearScale([xDomain.lo, xDomain.hi], [0, innerW]);
  const yAbs = Math.max(Math.abs(yDomain.lo), Math.abs(yDomain.hi), 1);
  const yScale = linearScale([-yAbs, yAbs], [innerH, 0]);

  const points: Point[] = finitePts.map((c) => [
    xScale(c.strike),
    yScale(c.netValue as number),
  ]);

  const xTicks = niceTicks(xDomain.lo, xDomain.hi, 6);
  const yTicks = niceTicks(-yAbs, yAbs, 5);

  return (
    <div style={panel}>
      <div
        style={{
          fontSize: 13,
          color: "var(--text-secondary)",
          marginBottom: 8,
        }}
      >
        {title}
      </div>
      <svg width={width} height={height} role="img" aria-label={title}>
        <title>{title}</title>
        <g transform={`translate(${PAD.left},${PAD.top})`}>
          {yTicks.map((t) => (
            <g key={`y-${t}`}>
              <line
                x1={0}
                x2={innerW}
                y1={yScale(t)}
                y2={yScale(t)}
                stroke="var(--border-dim)"
                strokeWidth={t === 0 ? 1 : 0.5}
              />
              <text
                x={-8}
                y={yScale(t)}
                dy="0.32em"
                textAnchor="end"
                fontSize={10}
                fill="var(--text-muted)"
              >
                {fmtMoneyAbbrev(t)}
              </text>
            </g>
          ))}

          {xTicks.map((t) => (
            <text
              key={`x-${t}`}
              x={xScale(t)}
              y={innerH + 18}
              textAnchor="middle"
              fontSize={10}
              fill="var(--text-muted)"
            >
              {t.toFixed(0)}
            </text>
          ))}

          {spot != null && xDomain.lo <= spot && spot <= xDomain.hi && (
            <>
              <line
                data-testid="spot-line"
                x1={xScale(spot)}
                x2={xScale(spot)}
                y1={0}
                y2={innerH}
                stroke={SPOT_COLOR}
                strokeWidth={1}
              />
              <text x={xScale(spot) + 6} y={12} fontSize={10} fill={SPOT_COLOR}>
                Price: {spot.toFixed(2)}
              </text>
            </>
          )}

          {flipStrike != null &&
            xDomain.lo <= flipStrike &&
            flipStrike <= xDomain.hi && (
              <>
                <line
                  data-testid="flip-line"
                  x1={xScale(flipStrike)}
                  x2={xScale(flipStrike)}
                  y1={0}
                  y2={innerH}
                  stroke={NET_COLOR}
                  strokeWidth={1}
                  strokeDasharray="4 3"
                />
                <text
                  x={xScale(flipStrike) + 6}
                  y={26}
                  fontSize={10}
                  fill={NET_COLOR}
                >
                  {yLabel} flip: {flipStrike.toFixed(2)}
                </text>
              </>
            )}

          {points.length >= 2 && (
            <path
              data-testid="net-line"
              d={pathFromPoints(points)}
              stroke={NET_COLOR}
              strokeWidth={2}
              fill="none"
            />
          )}
          {points.length === 1 && (
            <circle
              data-testid="net-point"
              cx={points[0][0]}
              cy={points[0][1]}
              r={4}
              fill={NET_COLOR}
            />
          )}
        </g>

        <text
          x={16}
          y={PAD.top + innerH / 2}
          textAnchor="middle"
          transform={`rotate(-90, 16, ${PAD.top + innerH / 2})`}
          fontSize={10}
          fill="var(--text-muted)"
        >
          {yLabel}
        </text>
      </svg>
    </div>
  );
}
