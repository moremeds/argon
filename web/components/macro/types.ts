import type { components } from "@/lib/types";

import type { ReplayVerdict } from "./replay";

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

/** One term behind a domain's confidence. Read via `kind`, never by term name --
 *  `ConfidenceArithmetic` documents why, and `models/macro.py:414-418` is the contract. */
export type MacroConfidenceReason =
  components["schemas"]["MacroConfidenceReason"];

/** One contradiction rule that fired inside ONE domain. Not to be confused with a
 *  `MacroSnapshotReason`, which is a defect BETWEEN domains -- the two live in different
 *  places for a reason and tab 00 keeps them in separate panels. */
export type MacroContradiction = components["schemas"]["MacroContradiction"];

export type MacroContextSnapshot =
  components["schemas"]["MacroContextSnapshotResponse"];

/**
 * The chain verdict's slot, three-state for the same reason a domain's is.
 *
 * `api.macroContextSnapshot` carries `allow404: true`, so "no snapshot was assembled for
 * this instant" comes back as `null` WITHOUT throwing, while a dead API throws. The page
 * this replaced caught the throw and returned `null` too, so both rendered as "chain never
 * assembled" -- a statement about the assembler made on the evidence of a broken network.
 * That is §4.6 of the port plan's collapse (`/gold`'s raw fetch shipping two failures as
 * one message) living on the macro page, and §9 invariant 2 forbids it.
 */
export type MacroSnapshotSlot = {
  value: MacroContextSnapshot | null;
  error?: string;
};

/**
 * One of tab 00's five publishers, with what it answered AND what that answer was for.
 *
 * Tabs 01 and 02 stand on one publisher each, so a single `ReplayStatus` above the content
 * says everything there is to say. Tab 00 stands on five, and they decline separately --
 * the chain snapshot can be absent for an instant four domains answered, and any one
 * domain can be absent while the chain is complete. So the verdict travels WITH the slot
 * rather than being summarised into one desk-level sentence, and the transmission-health
 * panel is where all five are read side by side.
 */
export type MacroOverviewSlot<T> = {
  value: T | null;
  error?: string;
  verdict: ReplayVerdict;
};

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
