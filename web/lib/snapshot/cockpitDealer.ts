// Cockpit dealer derivations, verbatim from
// app/cockpit/[ticker]/CockpitDealerTab.tsx (groupByExpiry / totals / peaks /
// maxAbs / exposureValue / netValue).
import { toNum } from "@/lib/formatters";
import type { CockpitDealerResponse } from "@/lib/api";

export type DealerPoint =
  NonNullable<NonNullable<CockpitDealerResponse>["points"]>[number];
export type DealerGreekKind = "vanna" | "charm";

/** Group by expiry (ascending), strikes ascending within each group. */
export function groupByExpiry(
  points: DealerPoint[],
): [string, DealerPoint[]][] {
  const map = new Map<string, DealerPoint[]>();
  for (const point of points) {
    const key = String(point.expiry);
    const rows = map.get(key) ?? [];
    rows.push(point);
    map.set(key, rows);
  }
  return Array.from(map.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([expiry, rows]) => [
      expiry,
      rows
        .slice()
        .sort((a, b) => (toNum(a.strike) ?? 0) - (toNum(b.strike) ?? 0)),
    ]);
}

/** Net vanna/charm totals over the group's points. */
export function totals(points: DealerPoint[]) {
  return points.reduce(
    (acc, point) => ({
      vanna: acc.vanna + (netValue(point, "vanna") ?? 0),
      charm: acc.charm + (netValue(point, "charm") ?? 0),
    }),
    { vanna: 0, charm: 0 },
  );
}

/** Peak |net| strike per greek; ties resolve to the first point in order. */
export function peaks(points: DealerPoint[]) {
  const peakVanna = maxAbs(points, "vanna");
  const peakCharm = maxAbs(points, "charm");
  return {
    vannaStrike: peakVanna ? toNum(peakVanna.strike) : null,
    charmStrike: peakCharm ? toNum(peakCharm.strike) : null,
  };
}

export function maxAbs(points: DealerPoint[], kind: DealerGreekKind) {
  let best: DealerPoint | null = null;
  let bestMagnitude = -1;
  for (const point of points) {
    const value = netValue(point, kind);
    const magnitude = value == null ? -1 : Math.abs(value);
    if (magnitude > bestMagnitude) {
      best = point;
      bestMagnitude = magnitude;
    }
  }
  return best;
}

export function exposureValue(
  point: DealerPoint,
  side: "call" | "put",
  kind: DealerGreekKind,
): number | null {
  if (side === "call" && kind === "vanna")
    return toNum(point.exposure_call_vanna);
  if (side === "put" && kind === "vanna")
    return toNum(point.exposure_put_vanna);
  if (side === "call" && kind === "charm")
    return toNum(point.exposure_call_charm);
  return toNum(point.exposure_put_charm);
}

/** Net = exposure_* when either side is present, else the raw call_/put_ sums. */
export function netValue(
  point: DealerPoint,
  kind: DealerGreekKind,
): number | null {
  const callExposure =
    kind === "vanna"
      ? toNum(point.exposure_call_vanna)
      : toNum(point.exposure_call_charm);
  const putExposure =
    kind === "vanna"
      ? toNum(point.exposure_put_vanna)
      : toNum(point.exposure_put_charm);
  if (callExposure != null || putExposure != null) {
    return (callExposure ?? 0) + (putExposure ?? 0);
  }
  const callRaw =
    kind === "vanna" ? toNum(point.call_vanna) : toNum(point.call_charm);
  const putRaw =
    kind === "vanna" ? toNum(point.put_vanna) : toNum(point.put_charm);
  if (callRaw == null && putRaw == null) return null;
  return (callRaw ?? 0) + (putRaw ?? 0);
}
