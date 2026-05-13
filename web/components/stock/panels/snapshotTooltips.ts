export type TooltipCopy = {
  definition: string;
  benchmark: string;
};

export const SNAPSHOT_TOOLTIPS: Record<string, TooltipCopy> = {
  alerts: {
    definition:
      "Number of UW flow alerts fired today. Each alert is a rule-based pattern flagged by UW (repeated hits, ask-side accumulation, etc.).",
    benchmark: "Median active ticker: 15–40. >100 = elevated.",
  },
  netPremium: {
    definition:
      "Sum of bull-premium minus bear-premium across today's flow alerts. Positive = aggregate alert flow is bullish.",
    benchmark: "Sign and bull/bear ratio matter more than absolute magnitude.",
  },
  bullPremium: {
    definition:
      "Premium spent on alerts UW labels bullish (calls bought at ask, puts sold at bid).",
    benchmark: "Compare to BEAR PREMIUM; >2× = directional buyer bias.",
  },
  bearPremium: {
    definition:
      "Premium on alerts UW labels bearish (puts bought at ask, calls sold at bid).",
    benchmark: "Compare to BULL PREMIUM.",
  },
  askPremium: {
    definition:
      "Premium where the trade was filled at the ask — aggressive buyer side. Higher than BID PREMIUM = real demand.",
    benchmark: "ASK > BID by >20% = informed buying signal.",
  },
  bidPremium: {
    definition:
      "Premium filled at the bid — seller-aggressor side. Often dealer overwriting or institutional yield-seeking.",
    benchmark: "ASK < BID = dealer / overwriter dominance.",
  },
  darkPoolPrints: {
    definition:
      "Number of off-exchange (ATS) trades today. Dark-pool prints don't move the lit tape but cluster around institutional accumulation levels.",
    benchmark:
      "Spikes vs 5-day median are more meaningful than absolute count.",
  },
  darkPoolNotional: {
    definition:
      "Total dollar value of off-exchange prints. Compare to today's lit-tape dollar volume on the same name.",
    benchmark:
      "Dark / lit ratio > 30% = unusually heavy off-exchange activity.",
  },
  sharesAvail: {
    definition:
      "Hard-to-borrow availability. Falling availability + rising fee rate is the classic short-squeeze setup.",
    benchmark: "<100k shares for a mid-cap is tight.",
  },
  feeRate: {
    definition: "Borrow fee for shorting this stock (% annualized).",
    benchmark:
      ">5% is meaningfully expensive; >20% is acute squeeze territory.",
  },
  rebateRate: {
    definition:
      "Rebate paid to long holders lending out shares. Inverse signal to fee rate.",
    benchmark: "High rebate = high borrow demand.",
  },
};
