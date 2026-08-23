import type { components } from "@/lib/types";

export type MacroDomainState = components["schemas"]["MacroDomainStateResponse"];

/**
 * One domain's slot on the desk.
 *
 * Three states, not two.  ``value`` present is an answer; ``error`` set is a request that
 * failed; both absent means the pipeline has simply never computed this domain.  Collapsing
 * the last two would report a missing engine as a broken network, and the operator would go
 * looking in the wrong place.
 */
export type MacroDomainSlot = {
  value: MacroDomainState | null;
  error?: string;
};

/** Causal order, which is the whole point of the page: inflation drives policy, policy
 *  drives the dollar, the dollar is one of gold's legs.  Rendering these as four peers is
 *  the shape this desk exists to replace. */
export const CAUSAL_ORDER = [
  "inflation",
  "policy_rates",
  "usd",
  "gold",
] as const;

export type MacroDomainKey = (typeof CAUSAL_ORDER)[number];

export const DOMAIN_LABEL: Record<MacroDomainKey, string> = {
  inflation: "Inflation",
  policy_rates: "Policy & Rates",
  usd: "USD Transmission",
  gold: "Gold Gate",
};

export const DOMAIN_LEDE: Record<MacroDomainKey, string> = {
  inflation: "What prices are doing, against the target.",
  policy_rates: "What the committee has done and what four separate paths expect next.",
  usd: "How policy transmits into the broad dollar.",
  gold: "Whether gold's measured relationships are holding at all.",
};
