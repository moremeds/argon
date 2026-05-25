import type { GexData } from "@/lib/regime/useGex";
import { fmtPrice } from "./format";

export function ExpectedRangeBar({ data }: { data: GexData }) {
  const { expected_range, levels, spot } = data;
  if (!expected_range.low || !expected_range.high) return null;

  const low = expected_range.low;
  const high = expected_range.high;
  const flip = levels.gex_flip?.strike;
  const magnet = levels.max_magnet?.strike;
  const accel = levels.max_accelerator?.strike;

  const allPoints = [low, high, spot];
  if (flip) allPoints.push(flip);
  if (magnet) allPoints.push(magnet);
  if (accel) allPoints.push(accel);
  const minVal = Math.min(...allPoints);
  const maxVal = Math.max(...allPoints);
  const range = maxVal - minVal || 1;
  const pct = (v: number) => ((v - minVal) / range) * 100;

  return (
    <div className="gex-range-container">
      <div className="gex-range-title">
        EXPECTED RANGE &mdash; {data.data_date}
      </div>
      <div className="gex-range-bar">
        <div
          className="gex-range-fill"
          style={{ left: `${pct(low)}%`, width: `${pct(high) - pct(low)}%` }}
        />
        {flip && (
          <div
            className="gex-range-marker"
            style={{ left: `${pct(flip)}%`, borderColor: "var(--warning)" }}
            title={`GEX FLIP: ${fmtPrice(flip)}`}
          />
        )}
        <div
          className="gex-range-marker"
          style={{ left: `${pct(spot)}%`, borderColor: "var(--signal-strong)" }}
          title={`SPOT: ${fmtPrice(spot)}`}
        />
        {magnet && (
          <div
            className="gex-range-marker"
            style={{
              left: `${pct(magnet)}%`,
              borderColor: "var(--signal-core)",
            }}
            title={`MAGNET: ${fmtPrice(magnet)}`}
          />
        )}
      </div>
      <div className="gex-range-labels">
        <span>{fmtPrice(low)}</span>
        {flip && (
          <span style={{ left: `${pct(flip)}%`, color: "var(--warning)" }}>
            {fmtPrice(flip)}
          </span>
        )}
        <span style={{ marginLeft: "auto" }}>{fmtPrice(high)}</span>
      </div>
      <div className="gex-range-sublabels">
        {accel && <span>MAX ACCEL</span>}
        {flip && <span>GEX FLIP</span>}
        <span>CLOSE</span>
        {magnet && <span>MAX MAGNET</span>}
      </div>
    </div>
  );
}
