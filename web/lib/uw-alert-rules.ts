/**
 * UW flow-alert rule slug → human-readable description.
 *
 * Falls back to the raw slug for unknown rules — extend this map as new
 * rule slugs appear in production.
 */
export const UW_ALERT_RULES: Record<string, string> = {
  RepeatedHits:
    "Same strike hit repeatedly throughout the day — suggests a single buyer accumulating with multiple child orders.",
  RepeatedHitsDescendingFill:
    "Repeated hits with each fill priced lower than the previous — price-sensitive accumulator.",
  RepeatedHitsAscendingFill:
    "Repeated hits with each fill priced higher than the previous — buyer chasing, urgency signal.",
  AskSideAccumulation:
    "Sustained ask-side aggressor flow on the same strike — directional buyer pressure.",
  BidSideAccumulation:
    "Sustained bid-side aggressor flow — overwriter or yield-seeker side, opposite directional read.",
  LowHistoricVolume:
    "Today's volume far exceeds the contract's historical norm — fresh attention on a previously inactive strike.",
  VolumeGreaterThanOpenInterest:
    "Day's volume > prior open interest — by definition, opening positioning rather than churn.",
};

export function describeAlertRule(slug: string): string {
  return UW_ALERT_RULES[slug] ?? slug;
}
