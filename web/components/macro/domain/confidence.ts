import type { components } from "@/lib/types";

export type ConfidenceReason = components["schemas"]["MacroConfidenceReason"];

/**
 * Confidence, as the multiplication it actually is.
 *
 * The board's t3 opens on this and says why: _"Confidence is not a black-box score, it is
 * auditable multiplication — every term names its evidence."_ A bare `conf 0.42` reads as
 * an opinion held weakly; the chain says WHICH input to go fix.
 *
 * Two rules this module exists to keep.
 *
 * **The chain is recomputed here and RECONCILED against the engine's own number.** It is
 * not restated from the board and it is not assumed to agree. If the product of the terms
 * ever stops equalling `confidence`, the panel says so rather than printing a tidy chain
 * beside a number it does not produce — a desk whose audit trail silently stops auditing
 * is worse than one with no audit trail, because it still looks like proof.
 *
 * **A term that did not fire is still shown.** The board's own chain omits
 * `revision_penalty` because it was 0 that day. Omitting a zero term makes "no input was
 * revised" indistinguishable from "revisions are not checked", and the second is a much
 * bigger claim. Every term renders; a penalty of 0 renders as `x (1 - 0.00)`.
 *
 * `informational` terms are carried but never multiplied. USD's `upstream_policy_rates`
 * is one: it reports the confidence of the state this engine cites, which is context for
 * the number, not an input to it.
 */
export type ChainTerm = {
  term: string;
  detail: string;
  /** As published: the multiplicand itself, or the penalty before it is subtracted. */
  raw: number;
  /** What actually enters the product: `raw` for a multiplicand, `1 - raw` for a penalty. */
  factor: number;
  kind: "multiplicand" | "penalty";
};

export type ConfidenceChain = {
  terms: ChainTerm[];
  informational: ConfidenceReason[];
  /** The product of every term's `factor`. */
  product: number;
  /** What the engine published, or null if it was unparseable. */
  reported: number | null;
  /** Does the chain reproduce the published number? */
  reconciles: boolean;
};

/** The engine publishes decimals as strings at full precision. */
function num(raw: string | number | null | undefined): number {
  const n = typeof raw === "string" ? Number(raw) : raw;
  return n === null || n === undefined || !Number.isFinite(n) ? NaN : n;
}

/** Float round-trip of a Decimal string is exact to ~1e-16 relative; 1e-6 is slack
 *  enough to never cry wolf and tight enough to catch a real disagreement. */
const RECONCILE_TOLERANCE = 1e-6;

export function confidenceChain(
  reasons: readonly ConfidenceReason[],
  confidence: string | number | null | undefined,
): ConfidenceChain {
  const terms: ChainTerm[] = [];
  const informational: ConfidenceReason[] = [];

  for (const r of reasons) {
    if (r.kind === "informational") {
      informational.push(r);
      continue;
    }
    const raw = num(r.value);
    if (!Number.isFinite(raw)) continue;
    terms.push({
      term: r.term,
      detail: r.detail,
      raw,
      factor: r.kind === "penalty" ? 1 - raw : raw,
      kind: r.kind,
    });
  }

  const product = terms.reduce((acc, t) => acc * t.factor, 1);
  const reported = num(confidence);
  const reportedOk = Number.isFinite(reported);

  return {
    terms,
    informational,
    product,
    reported: reportedOk ? reported : null,
    // An unparseable confidence cannot be reconciled against, and must not read as
    // agreement by default.
    reconciles:
      reportedOk &&
      terms.length > 0 &&
      Math.abs(product - reported) < RECONCILE_TOLERANCE,
  };
}

/**
 * The falsifier window, as the board's "confidence repair table".
 *
 * One row per term that is currently costing confidence, answering the question the board
 * pre-registers: _what event lifts this, and to what_. Each row is the SAME product with
 * exactly one term set to its clear value — so the table is arithmetic on numbers already
 * fetched, which is why the panel is tagged `COMPUTED` and shows its formula.
 *
 * The board is explicit about the boundary this respects: it pre-registers only
 * _"state/conf sensitivity (computable), never hike probabilities (those would be
 * invented)"_. Nothing here estimates whether the event happens, or when.
 *
 * A term already at its clear value produces no row — there is nothing to repair.
 */
export type RepairRow = {
  term: string;
  /** The engine's own words for what is costing the confidence. */
  detail: string;
  /** Confidence if this one term cleared, everything else unchanged. */
  to: number;
};

export type RepairTable = {
  from: number;
  rows: RepairRow[];
  /** Every term at its clear value. `null` when nothing is degraded. */
  allClear: number | null;
};

export function repairTable(chain: ConfidenceChain): RepairTable {
  const degraded = chain.terms.filter((t) => t.factor < 1);
  const rows = degraded.map((target) => ({
    term: target.term,
    detail: target.detail,
    to: chain.terms.reduce(
      (acc, t) => acc * (t.term === target.term ? 1 : t.factor),
      1,
    ),
  }));
  return {
    from: chain.product,
    rows,
    allClear: degraded.length > 0 ? 1 : null,
  };
}

/** Two decimals, the board's own precision for a confidence. */
export function fmtConfidence(value: number | null): string {
  return value === null || !Number.isFinite(value) ? "—" : value.toFixed(2);
}
