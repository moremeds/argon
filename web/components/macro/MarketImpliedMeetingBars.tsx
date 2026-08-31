import type { components } from "@/lib/types";

type PolicyPathPoint = components["schemas"]["PolicyPathPoint"];
type ProbabilityBucket = components["schemas"]["PolicyPathProbabilityBucket"];

function finiteProbability(bucket: ProbabilityBucket): number | null {
  const probability = Number(bucket.probability_percent);
  return Number.isFinite(probability) ? probability : null;
}

function bucketClass(label: string): string {
  if (/hold/i.test(label)) return "hd";
  if (/cut/i.test(label)) return "ct";
  return "hk";
}

function probabilityLabel(bucket: ProbabilityBucket): string {
  const probability = finiteProbability(bucket);
  return `${bucket.label} ${probability === null ? "n/a" : probability.toFixed(1)}%`;
}

function rateLabel(value: string): string {
  const rate = Number(value);
  return Number.isFinite(rate) ? `${rate.toFixed(4)} %` : "n/a";
}

/**
 * One publisher-bound rendering contract for the Overview and Fed tabs.
 *
 * The full distribution remains in the accessible name. Only positive finite buckets
 * become visual segments: a publisher-reported 0% outcome is evidence, but it has no
 * geometric width and must not acquire one through label padding.
 */
export function MarketImpliedMeetingBars({
  points,
}: {
  points: PolicyPathPoint[];
}) {
  return (
    <>
      {points.map((point) => {
        const buckets = point.probability_distribution ?? [];
        const visibleBuckets = buckets
          .map((bucket) => ({ bucket, probability: finiteProbability(bucket) }))
          .filter(
            (
              entry,
            ): entry is { bucket: ProbabilityBucket; probability: number } =>
              entry.probability !== null && entry.probability > 0,
          );
        const meetingLabel = point.horizon_date ?? point.horizon;

        return (
          <div className="meet" key={`${point.horizon}-${meetingLabel}`}>
            <div className="meet-h">
              <b>{meetingLabel}</b>
              <span className="num">implied {rateLabel(point.rate_percent)}</span>
            </div>
            <div
              className="pbar"
              data-testid="market-implied-probability-bar"
              aria-label={`Market-implied probability distribution for ${meetingLabel}: ${buckets
                .map(probabilityLabel)
                .join(", ")}`}
            >
              {visibleBuckets.map(({ bucket, probability }) => (
                <span
                  key={bucket.label}
                  className={bucketClass(bucket.label)}
                  data-probability-segment={bucket.label}
                  style={{ flexBasis: 0, flexGrow: probability }}
                  title={probabilityLabel(bucket)}
                >
                  {bucket.label} · {probability.toFixed(1)} %
                </span>
              ))}
            </div>
          </div>
        );
      })}
    </>
  );
}
