"use client";
import type { components } from "@/lib/types";
import { toNum } from "@/lib/formatters";
import { useLiveSpot } from "@/components/watchlist/LiveSpotsProvider";
import GexCurvatureChart from "@/components/shared/GexCurvatureChart";
import type { GexBucket } from "@/lib/regime/useGex";

type Report = components["schemas"]["SingleStockReport"];

const MAX_WINDOW_PCT = 0.15;
/** Fraction of total |GEX| the rendered window must contain. */
const MASS_COVERAGE = 0.98;
/** Never clip tighter than this, or a single dominant strike collapses the plot. */
const MIN_WINDOW_PCT = 0.02;
/**
 * Below this many surviving strikes the focused window is useless — the
 * curvature stencil needs 3 points and the chart needs 2 to draw a line at
 * all. Reachable on low-priced tickers, where ±2% of a $5 spot spans less
 * than one $1 strike increment. Fall back to the full candidate set.
 */
const MIN_STRIKES = 5;

/**
 * Aggregate the per-expiry strike curve into one net-GEX value per strike,
 * clip to the strike span that actually carries gamma, and tag the level
 * strikes so the shared chart draws its rules and markers.
 *
 * Two departures from the regime (index) path, both forced by single-name
 * data shape:
 *
 * - **No MIN_ABS_GEX floor.** The curvature field is a continuous line, so
 *   dropping thin strikes puts fake kinks in it. The old bar chart could
 *   drop them freely — its rows were independent.
 * - **Adaptive window instead of a fixed ±15%.** Single-name and ETF gamma
 *   concentrates within ~1–2% of spot, so a fixed wide window renders as a
 *   dead flat line with one spike. Grow outward from spot until the window
 *   holds MASS_COVERAGE of total |GEX|, then clamp to [MIN, MAX]_WINDOW_PCT.
 *   SPX-style broad profiles naturally hit the max.
 *
 * Exported for unit testing.
 */
export function buildStockGexProfile(
  curve: Report["strike_gex_curve"],
  spot: number,
  levels: Report["market_structure_levels"],
): GexBucket[] {
  const perStrike = new Map<number, number>();
  for (const b of curve ?? []) {
    const s = toNum(b.strike);
    const g = toNum(b.net_gex);
    if (s == null || g == null) continue;
    perStrike.set(s, (perStrike.get(s) ?? 0) + g);
  }

  const callWall = levels?.call_wall ? toNum(levels.call_wall.strike) : null;
  const putWall = levels?.put_wall ? toNum(levels.put_wall.strike) : null;
  const flip = levels?.gex_flip ? toNum(levels.gex_flip.strike) : null;

  // Everything is decided on ABSOLUTE distance from spot, never on a
  // percentage round-trip. Deriving a radius from a strike, converting it to
  // a percent, then rebuilding a bound as spot*(1±pct) loses the boundary to
  // floating point: for spot=10 and a dominant strike at 10.33, the rebuilt
  // bound is 10.329999999999998 and the window that was computed to hold 98%
  // of the gamma ends up holding 1% — it drops the very strike that set it.
  const maxRadius = spot * MAX_WINDOW_PCT;
  const candidates = Array.from(perStrike.entries())
    .filter(([s]) => Math.abs(s - spot) <= maxRadius)
    .sort((a, b) => a[0] - b[0]);

  const totalMass = candidates.reduce((acc, [, g]) => acc + Math.abs(g), 0);
  let radius = maxRadius;
  if (totalMass > 0) {
    // Walk outward from spot until MASS_COVERAGE is met; the last strike
    // taken sets the radius, and is itself kept (the filter is inclusive).
    const byDistance = [...candidates].sort(
      (a, b) => Math.abs(a[0] - spot) - Math.abs(b[0] - spot),
    );
    let acc = 0;
    let reached = 0;
    for (const [s, g] of byDistance) {
      acc += Math.abs(g);
      reached = Math.abs(s - spot);
      if (acc >= totalMass * MASS_COVERAGE) break;
    }
    radius = Math.min(maxRadius, Math.max(spot * MIN_WINDOW_PCT, reached));
  }

  const clipped = candidates.filter(([s]) => Math.abs(s - spot) <= radius);
  // Focusing must never leave too little to draw — see MIN_STRIKES. Widen to
  // the nearest-to-spot MIN_STRIKES rather than snapping back to the full
  // ±MAX_WINDOW_PCT set, so the view stays as tight as the data allows.
  const rendered =
    clipped.length >= MIN_STRIKES
      ? clipped
      : [...candidates]
          .sort((a, b) => Math.abs(a[0] - spot) - Math.abs(b[0] - spot))
          .slice(0, MIN_STRIKES)
          .sort((a, b) => a[0] - b[0]);

  return rendered.map(([strike, net_gex]) => ({
    strike,
    call_gex: 0,
    put_gex: 0,
    net_gex,
    pct_from_spot: ((strike - spot) / spot) * 100,
    tag:
      strike === flip
        ? "GEX FLIP"
        : strike === callWall
          ? "CALL WALL"
          : strike === putWall
            ? "PUT WALL"
            : null,
  }));
}

export function GexProfileChart({ report }: { report: Report }) {
  // Live spot anchors the profile so it ticks with the WS feed; scan-time
  // spot is the fallback.
  const live = toNum(useLiveSpot(report.ticker)?.spot);
  const spot = live ?? toNum(report.market_structure.spot);

  if (spot == null || spot <= 0) {
    return (
      <div className="gex-profile-chart">
        <div style={{ fontSize: 12, color: "var(--text-secondary)" }}>
          GEX Profile — Net gamma by strike
        </div>
        <div
          style={{ color: "var(--text-muted)", fontSize: 12, marginTop: 12 }}
        >
          Spot unavailable — strike profile cannot be anchored.
        </div>
      </div>
    );
  }

  const profile = buildStockGexProfile(
    report.strike_gex_curve,
    spot,
    report.market_structure_levels,
  );

  // The flip is an interpolated zero-crossing and often falls between listed
  // strikes, so pass it explicitly rather than relying on a strike-tag match.
  const flip = report.market_structure_levels?.gex_flip
    ? toNum(report.market_structure_levels.gex_flip.strike)
    : null;

  // GexCurvatureChart brings its own panel chrome — no wrapper box here.
  return <GexCurvatureChart profile={profile} spot={spot} flipStrike={flip} />;
}
