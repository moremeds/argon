import type { components } from "@/lib/types";
import styles from "./RatesDesk.module.css";
import { fmtSigned, fmtValue, toFiniteNumber } from "./format";

type CurvePoint = components["schemas"]["RatesCurvePoint"];

export function RatesCurveChart({ points }: { points: CurvePoint[] }) {
  const numeric = points
    .map((point, index) => ({
      point,
      index,
      value: toFiniteNumber(point.value, Number.NaN),
    }))
    .filter((item) => Number.isFinite(item.value));

  const min = numeric.length ? Math.min(...numeric.map((item) => item.value)) : 0;
  const max = numeric.length ? Math.max(...numeric.map((item) => item.value)) : 1;
  const span = Math.max(max - min, 0.25);
  const width = 760;
  const height = 260;
  const padX = 42;
  const padY = 28;

  const path = numeric
    .map((item) => {
      const x =
        padX +
        (item.index / Math.max(points.length - 1, 1)) * (width - padX * 2);
      const y = height - padY - ((item.value - min) / span) * (height - padY * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  return (
    <div className={styles.curveGrid}>
      <div className={styles.chartPanel} aria-label="Yield curve chart">
        <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="US Treasury yield curve">
          <rect x="0" y="0" width={width} height={height} rx="8" fill="#fff" />
          {[0, 0.25, 0.5, 0.75, 1].map((tick) => {
            const y = padY + tick * (height - padY * 2);
            return (
              <line
                key={tick}
                x1={padX}
                x2={width - padX}
                y1={y}
                y2={y}
                stroke="#ebe8f4"
              />
            );
          })}
          {path ? (
            <polyline
              points={path}
              fill="none"
              stroke="#ff7a5c"
              strokeWidth="4"
              strokeLinejoin="round"
              strokeLinecap="round"
            />
          ) : null}
          {numeric.map((item) => {
            const x =
              padX +
              (item.index / Math.max(points.length - 1, 1)) * (width - padX * 2);
            const y =
              height - padY - ((item.value - min) / span) * (height - padY * 2);
            return (
              <g key={item.point.tenor}>
                <circle cx={x} cy={y} r="5" fill="#312d4b" />
                <text x={x} y={height - 8} textAnchor="middle" className={styles.svgLabel}>
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
                <td>{fmtSigned(point.delta_1d_bps, "bps")}</td>
                <td>{fmtSigned(point.delta_1w_bps, "bps")}</td>
                <td>{fmtSigned(point.delta_1m_bps, "bps")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
