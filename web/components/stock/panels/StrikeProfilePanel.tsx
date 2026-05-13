import type { components } from "@/lib/types";
import { linearScale } from "@/lib/svgChart";
import { AnalyticalSeriesPanel } from "./AnalyticalSeriesPanel";

type ChainRow = components["schemas"]["OptionChainPerStrikeRow"];

type Props = {
  title: string;
  metric: "volume" | "oi";
  rows: ChainRow[];
  selectedExpiries: string[]; // ISO YYYY-MM-DD
  strikeRangePct: number; // e.g. 0.30 = ±30%
  spot: number;
};

const WIDTH = 560;
const HEIGHT = 240;
const PAD = { top: 16, right: 16, bottom: 26, left: 40 };

export function StrikeProfilePanel({
  title,
  metric,
  rows,
  selectedExpiries,
  strikeRangePct,
  spot,
}: Props) {
  const minStrike = spot * (1 - strikeRangePct);
  const maxStrike = spot * (1 + strikeRangePct);
  const callKey = metric === "volume" ? "call_volume" : "call_oi";
  const putKey = metric === "volume" ? "put_volume" : "put_oi";

  const selected = new Set(selectedExpiries);

  // Aggregate by strike across selected expiries.
  const byStrike = new Map<number, { call: number; put: number }>();
  for (const r of rows) {
    if (!selected.has(r.expiry)) continue;
    const s = Number(r.strike);
    if (s < minStrike || s > maxStrike) continue;
    const slot = byStrike.get(s) ?? { call: 0, put: 0 };
    slot.call += Number(r[callKey] ?? 0);
    slot.put += Number(r[putKey] ?? 0);
    byStrike.set(s, slot);
  }

  const sorted = [...byStrike.entries()].sort(([a], [b]) => a - b);
  const maxBar = Math.max(1, ...sorted.flatMap(([, v]) => [v.call, v.put]));

  const innerW = WIDTH - PAD.left - PAD.right;
  const x = linearScale([minStrike, maxStrike], [PAD.left, PAD.left + innerW]);
  const yCall = linearScale([0, maxBar], [HEIGHT / 2, PAD.top]); // up
  const yPut = linearScale([0, maxBar], [HEIGHT / 2, HEIGHT - PAD.bottom]); // down
  const barW = Math.max(2, innerW / Math.max(sorted.length, 1) - 2);

  // Bucket math: calls ITM when strike < spot; puts ITM when strike > spot.
  // ATM (strike == spot) routes to OTM for both — matches the panel's spec.
  let itmCall = 0,
    otmCall = 0,
    itmPut = 0,
    otmPut = 0;
  for (const [strike, v] of sorted) {
    if (strike < spot) {
      itmCall += v.call;
      otmPut += v.put;
    } else if (strike > spot) {
      otmCall += v.call;
      itmPut += v.put;
    } else {
      otmCall += v.call;
      otmPut += v.put;
    }
  }

  return (
    <AnalyticalSeriesPanel
      title={title}
      subtitle={`${selectedExpiries.length} expirie(s) · ±${(strikeRangePct * 100).toFixed(0)}% spot`}
    >
      <svg
        role="img"
        aria-label={title}
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        style={{ width: "100%", height: "auto" }}
      >
        <title>{title}: calls (green, above 0) / puts (red, below 0)</title>
        {/* zero line */}
        <line
          x1={PAD.left}
          x2={PAD.left + innerW}
          y1={HEIGHT / 2}
          y2={HEIGHT / 2}
          stroke="var(--border-dim)"
        />
        {/* spot marker */}
        <line
          x1={x(spot)}
          x2={x(spot)}
          y1={PAD.top}
          y2={HEIGHT - PAD.bottom}
          stroke="var(--text-muted)"
          strokeDasharray="3 3"
        />
        {sorted.map(([strike, v]) => (
          <g key={strike}>
            <rect
              x={x(strike) - barW / 2}
              y={yCall(v.call)}
              width={barW}
              height={HEIGHT / 2 - yCall(v.call)}
              fill="var(--positive)"
            />
            <rect
              x={x(strike) - barW / 2}
              y={HEIGHT / 2}
              width={barW}
              height={yPut(v.put) - HEIGHT / 2}
              fill="var(--negative)"
            />
          </g>
        ))}
      </svg>

      <table
        style={{
          width: "100%",
          fontFamily: "var(--font-mono)",
          fontSize: 11,
          marginTop: 8,
        }}
      >
        <thead>
          <tr style={{ color: "var(--text-muted)" }}>
            <th></th>
            <th>Total</th>
            <th>ITM</th>
            <th>OTM</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Calls</td>
            <td data-testid="calls-total">{itmCall + otmCall}</td>
            <td data-testid="calls-itm">{itmCall}</td>
            <td data-testid="calls-otm">{otmCall}</td>
          </tr>
          <tr>
            <td>Puts</td>
            <td data-testid="puts-total">{itmPut + otmPut}</td>
            <td data-testid="puts-itm">{itmPut}</td>
            <td data-testid="puts-otm">{otmPut}</td>
          </tr>
          <tr>
            <td>Total</td>
            <td>{itmCall + otmCall + itmPut + otmPut}</td>
            <td>{itmCall + itmPut}</td>
            <td>{otmCall + otmPut}</td>
          </tr>
        </tbody>
      </table>
    </AnalyticalSeriesPanel>
  );
}
