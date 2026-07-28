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
  for (const b of curve) {
    const s = toNum(b.strike);
    const g = toNum(b.net_gex);
    if (s == null || g == null) continue;
    perStrike.set(s, (perStrike.get(s) ?? 0) + g);
  }

  const callWall = levels?.call_wall ? toNum(levels.call_wall.strike) : null;
  const putWall = levels?.put_wall ? toNum(levels.put_wall.strike) : null;
  const flip = levels?.gex_flip ? toNum(levels.gex_flip.strike) : null;

  // Widest allowed candidate set, then shrink to the gamma-carrying span.
  const candidates = Array.from(perStrike.entries())
    .filter(
      ([s]) =>
        s >= spot * (1 - MAX_WINDOW_PCT) && s <= spot * (1 + MAX_WINDOW_PCT),
    )
    .sort((a, b) => a[0] - b[0]);

  const totalMass = candidates.reduce((acc, [, g]) => acc + Math.abs(g), 0);
  let windowPct = MAX_WINDOW_PCT;
  if (totalMass > 0) {
    // Sort by distance from spot and take strikes until MASS_COVERAGE is met;
    // the last one taken sets the radius.
    const byDistance = [...candidates].sort(
      (a, b) => Math.abs(a[0] - spot) - Math.abs(b[0] - spot),
    );
    let acc = 0;
    let radius = 0;
    for (const [s, g] of byDistance) {
      acc += Math.abs(g);
      radius = Math.abs(s - spot);
      if (acc >= totalMass * MASS_COVERAGE) break;
    }
    windowPct = Math.min(
      MAX_WINDOW_PCT,
      Math.max(MIN_WINDOW_PCT, radius / spot),
    );
  }

  const lo = spot * (1 - windowPct);
  const hi = spot * (1 + windowPct);

  return candidates
    .filter(([s]) => s >= lo && s <= hi)
    .map(([strike, net_gex]) => ({
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

  // GexCurvatureChart brings its own panel chrome — no wrapper box here.
  return <GexCurvatureChart profile={profile} spot={spot} />;
}
