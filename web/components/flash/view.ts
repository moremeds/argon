import type { AgentRunResponse } from "@/lib/api";

/**
 * option-wizard's `view_jsonb`, mirrored by hand.
 *
 * HAND-WRITTEN ON PURPOSE. The two repos deploy independently, so a generated
 * binding would make every helium field rename an argon BUILD failure instead
 * of a rendered gap. A page one section short is recoverable within the hour;
 * a red build on the other repo's release schedule is not.
 *
 * Every field is optional except `date`. That is not laziness — it is the
 * contract: helium ships a document, argon renders what it recognises and
 * leaves an honest hole where it does not.
 */

/** The shape this build knows how to draw. */
export const SUPPORTED_SCHEMA_VERSION = 1;

export interface Leg {
  right: "call" | "put";
  action: "buy" | "sell";
  strike: number;
  expiry: string;
  ratio?: number;
  mid?: number;
}

export type Pricing =
  | {
      kind: "priced";
      /** Per share. Positive = credit received, negative = debit paid. */
      net: number;
      /** Per contract. `null` means unbounded — never a large number. */
      maxGain: number | null;
      maxLoss: number | null;
      breakevens: number[];
      pnlAt: { pct: number | null; spot: number; pnl: number }[];
    }
  | { kind: "unpriced"; reason: string }
  | { kind: "invalid"; reason: string };

export interface Invalidation {
  level: number;
  side: "above" | "below";
}

export interface CandidateView {
  id: string;
  ticker: string;
  strategy: string;
  expiry?: string;
  dte: number | null;
  legs: Leg[];
  pricing: Pricing;
  width?: number;
  invalidation?: Invalidation[];
  target?: Invalidation;
  entry?: Invalidation;
  unchecked?: string;
  spot?: number;
  rationale?: string;
  earnings?: string;
}

export interface TapeItem {
  label: string;
  value: string;
  /** The string the tenant wrote. Its sign is read off the string, not re-derived. */
  change?: string | null;
  positive?: boolean;
  source?: string;
}

export interface Section {
  title: string;
  body: string;
}

export interface GammaLevel {
  strike: number;
  label: string;
  role?: string;
  value: number;
}

export interface GammaProfile {
  ticker: string;
  spot?: string | number;
  levels: GammaLevel[];
}

export interface BriefView {
  schemaVersion?: number;
  date: string;
  tenant?: string;
  outcome?: string;
  headline?: string;
  asOf?: string;
  tape?: TapeItem[];
  tapeSource?: string;
  lead?: string;
  schedule?: Section[];
  overnight?: string[];
  sections?: Section[];
  coverage?: Section;
  regime?: Section[];
  candidates?: CandidateView[];
  gamma?: GammaProfile[];
  riskList?: Section[];
  decision?: { label: string; value: string }[];
  degradation?: string[];
  empty?: boolean;
  charts?: Record<string, unknown>;
  edited?: string;
}

/**
 * `null` when this build cannot render the version that arrived.
 *
 * The caller then SAYS which version came and which it understands. A silently
 * blank page is the one outcome a versioned document exists to prevent —
 * that is the whole reason `schema_version` is a column and not a comment.
 */
export function asBriefView(run: AgentRunResponse): BriefView | null {
  if (run.schema_version !== SUPPORTED_SCHEMA_VERSION) return null;
  const view = run.view as Partial<BriefView> | null | undefined;
  if (!view || typeof view !== "object") return null;
  return {
    ...view,
    date: view.date ?? String(run.run_day),
    headline: view.headline ?? run.headline,
    outcome: view.outcome ?? run.outcome,
    tenant: view.tenant ?? run.tenant,
  };
}
