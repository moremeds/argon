import type { components } from "@/lib/types";
import styles from "./RatesDesk.module.css";
import { fmtSigned, fmtValue, toFiniteNumber } from "./format";

type CurvePoint = components["schemas"]["RatesCurvePoint"];

type CurveSeries = {
  id: string;
  label: string;
  className: string;
  values: Array<{ point: CurvePoint; index: number; value: number }>;
};

function priorValue(point: CurvePoint, deltaBps: unknown): number {
  const value = toFiniteNumber(point.value, Number.NaN);
  const delta = toFiniteNumber(deltaBps, Number.NaN);
  if (!Number.isFinite(value) || !Number.isFinite(delta)) return Number.NaN;
  return value - delta / 100;
}

function deltaClass(value: unknown): string {
  const n = toFiniteNumber(value, Number.NaN);
  if (!Number.isFinite(n) || n === 0) return styles.deltaNeutral;
  return n > 0 ? styles.deltaPositive : styles.deltaNegative;
}

export function RatesCurveChart({ points }: { points: CurvePoint[] }) {
  const series: CurveSeries[] = [
    {
      id: "current",
      label: "Current",
      className: styles.currentCurve,
      values: points.map((point, index) => ({
        point,
        index,
        value: toFiniteNumber(point.value, Number.NaN),
      })),
    },
    {
      id: "week",
      label: "1W ago",
      className: styles.weekCurve,
      values: points.map((point, index) => ({
        point,
        index,
        value: priorValue(point, point.delta_1w_bps),
      })),
    },
    {
      id: "month",
      label: "1M ago",
      className: styles.monthCurve,
      values: points.map((point, index) => ({
        point,
        index,
        value: priorValue(point, point.delta_1m_bps),
      })),
    },
  ].map((curve) => ({
    ...curve,
    values: curve.values.filter((item) => Number.isFinite(item.value)),
  }));

  const numeric = series.flatMap((curve) => curve.values);
  const current = series[0]?.values ?? [];

  const min = numeric.length
    ? Math.min(...numeric.map((item) => item.value))
    : 0;
  const max = numeric.length
    ? Math.max(...numeric.map((item) => item.value))
    : 1;
  const span = Math.max(max - min, 0.25);
  const width = 760;
  const height = 320;
  const padX = 58;
  const padTop = 22;
  const padBottom = 38;
  const plotHeight = height - padTop - padBottom;
  const tickValues = [1, 0.75, 0.5, 0.25, 0].map((ratio) => min + span * ratio);

  const pathFor = (values: CurveSeries["values"]) =>
    values
      .map((item) => {
        const x =
          padX +
          (item.index / Math.max(points.length - 1, 1)) * (width - padX * 2);
        const y = padTop + (1 - (item.value - min) / span) * plotHeight;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(" ");

  const positionFor = (item: { index: number; value: number }) => {
    const x =
      padX + (item.index / Math.max(points.length - 1, 1)) * (width - padX * 2);
    const y = padTop + (1 - (item.value - min) / span) * plotHeight;
    return { x, y };
  };

  return (
    <div className={styles.curveGrid}>
      <div className={styles.chartPanel} aria-label="Yield curve chart">
        <div className={styles.chartHeader}>
          <strong>PAR yield curve overlay</strong>
          <div
            className={styles.chartLegend}
            aria-label="Yield curve comparison legend"
          >
            {series.map((curve) => (
              <span key={curve.id}>
                <i className={curve.className} />
                {curve.label}
              </span>
            ))}
          </div>
        </div>
        <svg
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-label="US Treasury yield curve"
        >
          <rect
            x="0"
            y="0"
            width={width}
            height={height}
            rx="8"
            fill="var(--bg-panel-raised)"
          />
          {tickValues.map((value) => {
            const y = padTop + (1 - (value - min) / span) * plotHeight;
            return (
              <g key={value.toFixed(3)}>
                <line
                  x1={padX}
                  x2={width - padX}
                  y1={y}
                  y2={y}
                  stroke="var(--border-dim)"
                />
                <text
                  x={padX - 12}
                  y={y + 4}
                  textAnchor="end"
                  className={styles.svgLabel}
                >
                  {value.toFixed(1)}
                </text>
              </g>
            );
          })}
          <line
            x1={padX}
            x2={padX}
            y1={padTop}
            y2={height - padBottom}
            stroke="var(--border-dim)"
          />
          {series
            .slice()
            .reverse()
            .map((curve) => {
              const path = pathFor(curve.values);
              return path ? (
                <polyline
                  key={curve.id}
                  points={path}
                  fill="none"
                  className={curve.className}
                  strokeWidth={curve.id === "current" ? "4" : "3"}
                  strokeLinejoin="round"
                  strokeLinecap="round"
                  strokeDasharray={curve.id === "month" ? "6 6" : undefined}
                />
              ) : null;
            })}
          {current.map((item) => {
            const { x, y } = positionFor(item);
            return (
              <g key={item.point.tenor}>
                <circle cx={x} cy={y} r="5" fill="var(--text-primary)" />
                <text
                  x={x}
                  y={height - 12}
                  textAnchor="middle"
                  className={styles.svgLabel}
                >
                  {item.point.tenor}
                </text>
              </g>
            );
          })}
        </svg>
      </div>

      <div className={styles.tableWrap}>
        <table className={styles.curveTable}>
          <thead>
            <tr>
              <th>Tenor</th>
              <th>Yield</th>
              <th>1D</th>
              <th>1W</th>
              <th>1M</th>
            </tr>
          </thead>
          <tbody>
            {points.map((point) => (
              <tr key={point.tenor}>
                <th scope="row">{point.tenor}</th>
                <td>{fmtValue(point.value, "%")}</td>
                <td className={deltaClass(point.delta_1d_bps)}>
                  {fmtSigned(point.delta_1d_bps, "bps")}
                </td>
                <td className={deltaClass(point.delta_1w_bps)}>
                  {fmtSigned(point.delta_1w_bps, "bps")}
                </td>
                <td className={deltaClass(point.delta_1m_bps)}>
                  {fmtSigned(point.delta_1m_bps, "bps")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
