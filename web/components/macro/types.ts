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

export type MacroContextSnapshot =
  components["schemas"]["MacroContextSnapshotResponse"];

// ``reasons`` and ``domains`` carry Pydantic defaults, so the generated schema marks
// them optional. Unwrapped here once rather than at every use site.
export type MacroSnapshotReason =
  NonNullable<MacroContextSnapshot["reasons"]>[number];

/** What each non-complete status means, in the operator's terms. The two refusals stay
 *  apart on purpose: "rates never ran" sends you to the scheduler, "rates ran but USD
 *  ignored it" sends you to the data, and one merged "degraded" would point you at the
 *  wrong one. */
export const STATUS_LEDE: Record<string, string> = {
  partial:
    "A domain is missing — its job failed or never ran. The domains that did answer are still their own honest answers.",
  incompatible:
    "A domain present below stood on an upstream answer that is not the one this snapshot holds. Every card can look current and the chain still be wrong.",
  stale:
    "The newest snapshot is older than the expected cadence, so this chain describes an earlier instant than the one you asked about.",
};
