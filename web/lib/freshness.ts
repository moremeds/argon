export type Freshness = "fresh" | "stale" | "dead";

type FreshnessThresholds = {
  freshMinutes: number;
  staleMinutes: number;
};

const DEFAULT_THRESHOLDS: FreshnessThresholds = {
  freshMinutes: 60,
  staleMinutes: 180,
};

export function bucketFreshness(
  scannedAt: string | null | undefined,
  now: Date = new Date(),
  thresholds: FreshnessThresholds = DEFAULT_THRESHOLDS,
): Freshness {
  if (!scannedAt) return "dead";
  const t = new Date(scannedAt).getTime();
  if (Number.isNaN(t)) return "dead";
  const ageMin = (now.getTime() - t) / 60_000;
  if (ageMin < thresholds.freshMinutes) return "fresh";
  if (ageMin < thresholds.staleMinutes) return "stale";
  return "dead";
}
