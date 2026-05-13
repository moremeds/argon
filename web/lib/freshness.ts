export type Freshness = "fresh" | "stale" | "dead";

export function bucketFreshness(
  scannedAt: string | null | undefined,
  now: Date = new Date(),
): Freshness {
  if (!scannedAt) return "dead";
  const t = new Date(scannedAt).getTime();
  if (Number.isNaN(t)) return "dead";
  const ageMin = (now.getTime() - t) / 60_000;
  if (ageMin < 60) return "fresh";
  if (ageMin < 180) return "stale";
  return "dead";
}
