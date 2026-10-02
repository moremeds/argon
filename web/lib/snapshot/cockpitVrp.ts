// Cockpit VRP derivations, verbatim from
// app/cockpit/[ticker]/CockpitVrpTab.tsx (vrpValues → meanStd → band → row z).
import { toNum } from "@/lib/formatters";
import type { CockpitVrpResponse } from "@/lib/api";

export type VrpPoint =
  NonNullable<NonNullable<CockpitVrpResponse>["points"]>[number];
export type VrpStats = { mean: number; std: number };

/** Population (not sample) standard deviation — verbatim. */
export function meanStd(values: number[]): VrpStats {
  if (!values.length) return { mean: 0, std: 0 };
  const mean = values.reduce((sum, value) => sum + value, 0) / values.length;
  const variance =
    values.reduce((sum, value) => sum + (value - mean) ** 2, 0) /
    values.length;
  return { mean, std: Math.sqrt(variance) };
}

/** Stats over the non-null points[].vrp. */
export function vrpStats(points: VrpPoint[]): VrpStats {
  const vrpValues = points
    .map((point) => toNum(point.vrp))
    .filter((value): value is number => value != null);
  return meanStd(vrpValues);
}

/** mean ± 0.5·sd band; undefined when sd = 0 (the component adds color). */
export function vrpBand(
  stats: VrpStats,
): { min: number; max: number } | undefined {
  if (stats.std > 0)
    return {
      min: stats.mean - 0.5 * stats.std,
      max: stats.mean + 0.5 * stats.std,
    };
  return undefined;
}

/** Per-row z; null when the value is missing or sd = 0. */
export function vrpZ(
  vrp: number | null,
  stats: VrpStats,
): number | null {
  return vrp != null && stats.std > 0 ? (vrp - stats.mean) / stats.std : null;
}
