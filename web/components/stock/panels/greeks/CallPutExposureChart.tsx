import {
  finiteDomain,
  linearScale,
  niceTicks,
  pathFromPoints,
  type Point,
} from "@/lib/svgChart";
import { fmtMoneyAbbrev } from "@/lib/formatters";

export type CallPutPoint = {
  strike: number;
  callValue: number | null;
  putValue: number | null;
};

type Props = {
  curve: CallPutPoint[];
  spot: number | null;
  yLabel: "Vanna" | "Charm";
  title: string;
  width?: number;
  height?: number;
};

const PAD = { top: 36, right: 24, bottom: 40, left: 64 };
const CALL_COLOR = "var(--positive)";
const PUT_COLOR = "var(--negative)";
const SPOT_COLOR = "var(--warning)";

export function CallPutExposureChart({
  curve,
  spot,
  yLabel,
  title,
  width = 560,
  height = 360,
}: Props) {
  const finiteCall = curve.filter(
    (c) =>
      Number.isFinite(c.strike) &&
      c.callValue != null &&
      Number.isFinite(c.callValue as number),
  );
  const finitePut = curve.filter(
    (c) =>
      Number.isFinite(c.strike) &&
      c.putValue != null &&
      Number.isFinite(c.putValue as number),
  );
  const finiteStrikes = curve.filter(
    (c) =>
      Number.isFinite(c.strike) && (c.callValue != null || c.putValue != null),
  );

  const panel: React.CSSProperties = {
    background: "var(--bg-panel)",
    border: "1px solid var(--border-dim)",
    borderRadius: 4,
    padding: 16,
    fontFamily: "var(--font-mono)",
  };

  if (finiteStrikes.length === 0) {
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

  const allY = [
    ...finiteCall.map((c) => c.callValue as number),
    ...finitePut.map((c) => c.putValue as number),
  ];
  const xDomain =
    finiteStrikes.length >= 2
      ? finiteDomain(finiteStrikes.map((c) => c.strike))!
      : (() => {
          const s = finiteStrikes[0].strike;
          const half = spot != null ? Math.abs(s - spot) || s * 0.05 : s * 0.05;
          return { lo: s - half, hi: s + half, count: 1 };
        })();
  const yDomain =
    allY.length >= 2
      ? finiteDomain(allY)!
      : (() => {
          const v = allY[0] != null ? Math.abs(allY[0]) : 1;
          return { lo: -v, hi: v, count: 1 };
        })();

  const innerW = width - PAD.left - PAD.right;
  const innerH = height - PAD.top - PAD.bottom;
  const xScale = linearScale([xDomain.lo, xDomain.hi], [0, innerW]);
  const yAbs = Math.max(Math.abs(yDomain.lo), Math.abs(yDomain.hi), 1);
  const yScale = linearScale([-yAbs, yAbs], [innerH, 0]);

  const callPoints: Point[] = finiteCall.map((c) => [
    xScale(c.strike),
    yScale(c.callValue as number),
  ]);
  const putPoints: Point[] = finitePut.map((c) => [
    xScale(c.strike),
    yScale(c.putValue as number),
  ]);

  const xTicks = niceTicks(xDomain.lo, xDomain.hi, 6);
  const yTicks = niceTicks(-yAbs, yAbs, 5);

  return (
    <div style={panel}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          marginBottom: 8,
        }}
      >
        <div style={{ fontSize: 13, color: "var(--text-secondary)" }}>
          {title}
        </div>
        <div style={{ display: "flex", gap: 12, fontSize: 11 }}>
          <span style={{ color: CALL_COLOR }}>— Call {yLabel}</span>
          <span style={{ color: PUT_COLOR }}>— Put {yLabel}</span>
        </div>
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

          {callPoints.length >= 2 && (
            <path
              data-testid="call-line"
              d={pathFromPoints(callPoints)}
              stroke={CALL_COLOR}
              strokeWidth={2}
              fill="none"
            />
          )}
          {callPoints.length === 1 && (
            <circle
              data-testid="call-point"
              cx={callPoints[0][0]}
              cy={callPoints[0][1]}
              r={4}
              fill={CALL_COLOR}
            />
          )}
          {putPoints.length >= 2 && (
            <path
              data-testid="put-line"
              d={pathFromPoints(putPoints)}
              stroke={PUT_COLOR}
              strokeWidth={2}
              fill="none"
            />
          )}
          {putPoints.length === 1 && (
            <circle
              data-testid="put-point"
              cx={putPoints[0][0]}
              cy={putPoints[0][1]}
              r={4}
              fill={PUT_COLOR}
            />
          )}
        </g>
      </svg>
    </div>
  );
}
