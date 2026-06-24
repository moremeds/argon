import type { GexData } from "@/lib/regime/useGex";
import { fmtPrice } from "./format";

type Mark = {
  key: string;
  value: number;
  name: string;
  color: string;
};

/**
 * Expected-move bar for the index: the green fill is the ±1σ 1-day expected
 * range (spot ± iv_1d), overlaid with the dealer levels that exist. Every
 * marker carries its OWN value + name label, absolutely positioned at the same
 * pct() as the tick — so a label always sits directly under its marker. Labels
 * drop to a second tier when two levels fall within ~12% of each other (flip,
 * close, spot and the magnets routinely cluster), instead of the old flex rows
 * that distributed text evenly and never lined up with the ticks.
 */
export function ExpectedRangeBar({ data }: { data: GexData }) {
  const { expected_range, levels, spot } = data;
  if (expected_range.low == null || expected_range.high == null) return null;

  const low = expected_range.low;
  const high = expected_range.high;
  const close =
    data.prev_close != null && data.prev_close > 0 ? data.prev_close : null;

  const marks: Mark[] = [];
  const push = (
    value: number | null | undefined,
    name: string,
    color: string,
    key: string,
  ) => {
    if (value != null && Number.isFinite(value))
      marks.push({ key, value, name, color });
  };
  push(levels.max_accelerator?.strike, "MAX ACCEL", "var(--fault)", "accel");
  push(levels.gex_flip?.strike, "GEX FLIP", "var(--warning)", "flip");
  push(close, "CLOSE", "var(--text-muted)", "close");
  push(spot, "SPOT", "var(--signal-strong)", "spot");
  push(levels.max_magnet?.strike, "MAX MAGNET", "var(--signal-core)", "magnet");

  // Axis spans the band AND every marker so nothing plots off-bar; 3% padding
  // keeps the edge labels inside the card.
  const pts = [low, high, ...marks.map((m) => m.value)];
  const lo = Math.min(...pts);
  const hi = Math.max(...pts);
  const padPct = (hi - lo || 1) * 0.03;
  const minVal = lo - padPct;
  const maxVal = hi + padPct;
  const axis = maxVal - minVal || 1;
  const pct = (v: number) => ((v - minVal) / axis) * 100;

  // Two-tier label stagger: walk left→right, bump a label to the lower tier
  // when it would land within 12% of the previous label on the same tier.
  const tierOf = new Map<string, number>();
  const lastTierPos: Record<number, number> = {};
  for (const m of [...marks].sort((a, b) => a.value - b.value)) {
    const p = pct(m.value);
    let tier = 0;
    if (lastTierPos[0] != null && p - lastTierPos[0] < 12) {
      tier = lastTierPos[1] == null || p - lastTierPos[1] >= 12 ? 1 : 0; // both crowded → ping-pong back to tier 0
    }
    lastTierPos[tier] = p;
    tierOf.set(m.key, tier);
  }

  const movePts = (high - low) / 2;
  const movePct = expected_range.iv_1d;

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
        {marks.map((m) => (
          <div
            key={m.key}
            className="gex-range-marker"
            style={{ left: `${pct(m.value)}%`, borderColor: m.color }}
            title={`${m.name}: ${fmtPrice(m.value)}`}
          />
        ))}
      </div>

      {/* value + name stacked directly under each marker (2-tier on collision) */}
      <div style={{ position: "relative", height: 54, marginTop: 6 }}>
        {marks.map((m) => (
          <div
            key={m.key}
            data-testid={`exp-range-label-${m.key}`}
            style={{
              position: "absolute",
              left: `${pct(m.value)}%`,
              top: (tierOf.get(m.key) ?? 0) * 26,
              transform: "translateX(-50%)",
              textAlign: "center",
              fontFamily: "var(--font-mono)",
              lineHeight: 1.2,
              whiteSpace: "nowrap",
            }}
          >
            <div style={{ fontSize: 10, color: m.color }}>
              {fmtPrice(m.value)}
            </div>
            <div style={{ fontSize: 9, color: "var(--text-muted)" }}>
              {m.name}
            </div>
          </div>
        ))}
      </div>

      <div
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          color: "var(--text-muted)",
          marginTop: 4,
        }}
      >
        Expected ±{fmtPrice(movePts)}
        {movePct != null ? ` (±${movePct.toFixed(2)}%)` : ""} · {fmtPrice(low)}{" "}
        – {fmtPrice(high)}
      </div>
    </div>
  );
}
