import type { AgentRunResponse } from "@/lib/api";
import { tickerSet } from "@/lib/flash/tickers";

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

/**
 * The shapes this build knows how to draw.
 *
 * THREE of them, deliberately. The producer and this consumer deploy on
 * separate schedules, so there is always a window where one is ahead: v1 puts
 * the target in prose and v2 puts it in `{level, side}` with the sentence moved
 * to `thesis`; v3 keeps every v2 key and ADDS the review blocks (`focus`,
 * `themes`, `rotation`, `oneThing`, `checks`, `footer`, `faults`). Refusing an
 * older version during that window would blank a page over a field that is
 * only differently spelled, and refusing v3 blanks a page whose v2 half argon
 * already knows how to draw.
 */
export const SUPPORTED_SCHEMA_VERSIONS: readonly number[] = [1, 2, 3];
/** @deprecated The newest shape; prefer `SUPPORTED_SCHEMA_VERSIONS`. */
export const SUPPORTED_SCHEMA_VERSION = 3;

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
  /** v2 writes a level and a side; v1 wrote a sentence. Both render. */
  target?: Invalidation | string;
  /** v2 only: what the run said it expects, in prose. */
  thesis?: string;
  /** v2 only: the date after which nothing can resolve. Display only. */
  resolutionDeadline?: string;
  entry?: Invalidation & { deadlineBars?: number };
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

/** One row of the day's event calendar, as the run recorded it. */
export interface ScheduleItem {
  /** "Today" / "Tomorrow" — printed once, on the row that opens the group. */
  group?: string;
  time: string;
  event: string;
  /** Consensus / prior, as one string. Absent is not zero. */
  consensus?: string;
}

/** One dated meeting on the futures-implied policy path. */
export interface PolicyStep {
  date: string;
  implied: string;
  band?: string;
  call?: string;
  probability?: string;
}

export interface PolicyPath {
  steps: PolicyStep[];
  /**
   * Printed verbatim. NEVER rewritten to "CME FedWatch": the recorded source
   * is Frenzy futures-implied, and relabelling it is a data-integrity fault.
   */
  source: string;
}

/** A tracked candidate as a supplement found it: id, state, prose. */
export interface StatusItem {
  title: string;
  /** 不变 / 加强 / 反转 / "not armed" — the tenant's word, not argon's. */
  state?: string;
  body: string;
}

/** One dealer-gamma row, as strings: they are the run's own formatting. */
export interface GexRow {
  ticker: string;
  spot?: string;
  flip?: string;
  magnet?: string;
  callWall?: string;
  putWall?: string;
}

export interface GammaProfile {
  ticker: string;
  spot?: string | number;
  levels: GammaLevel[];
}

/* ---------- v3: the review blocks ---------- */

/**
 * One name the run is watching, and why it is on the list.
 *
 * `openCall` is helium's own id for the call this row continues
 * (`2026-09-04-close-focus-ADBE`); `sticky` marks a name the run kept rather
 * than picked fresh. Both are the run's bookkeeping, printed, never derived.
 */
export interface FocusRow {
  ticker: string;
  event: string;
  why?: string;
  /** 0–100, as helium computed it. */
  ivRank?: number;
  openCall?: string;
  sticky?: boolean;
}

/** The focus list, with the run's own count of how much of it changed. */
export interface FocusBlock {
  period?: "weekly" | "daily" | string;
  rows: FocusRow[];
  /** Why the list is short of its target length, when it is. */
  shortfall?: string;
  churn?: number;
}

/**
 * A standing theme and the condition that would end it.
 *
 * The excess figures are STRINGS ("+6.5%") — helium's own formatting, sign and
 * unit included, so argon never re-derives a number it did not measure.
 */
export interface Theme {
  id: string;
  /** continue / strengthen / fade / reverse — the run's word, lowercased. */
  token: string;
  excess1w?: string;
  excessSinceEntered?: string;
  leadership?: string;
  why?: string;
  kill?: string;
  killMet?: boolean;
}

/**
 * One basket row. Every number is nullable: a symbol whose bars did not
 * arrive is `untested`, carrying the reason instead of a figure. A null is
 * never drawn as a zero.
 */
export interface RotationRow {
  symbol: string;
  label: string;
  w1: number | null;
  w4: number | null;
  w12: number | null;
  excess1w: number | null;
  excess4w: number | null;
  excess12w: number | null;
  /** Present only when the row has no numbers, e.g. "no bar on 2026-08-28". */
  untested?: string;
}

export interface Rotation {
  asOf?: string;
  /** The symbol every excess column is measured against. */
  benchmark?: string;
  rows: RotationRow[];
}

/** What the run read, from where, and what it could not reach. */
export interface BriefFooter {
  coverage?: string[];
  asOf?: string[];
  notes?: string[];
}

/** The single claim the run is making today, and yesterday's scoring line. */
export interface OneThing {
  title: string;
  body: string;
  why?: string;
  /**
   * How yesterday's three checks came out, as ONE sentence helium wrote.
   * The scoring is prose on purpose: no stored run carries a per-check
   * verdict field, so argon prints the line rather than inventing a state.
   */
  checksLine?: string;
}

/** One falsifiable check on the claim: a series, the level it sits at, the question. */
export interface Check {
  series?: string;
  /** A string, not a number: helium writes "50.7" for a probability and "14.32" for an index. */
  level?: string;
  text: string;
}

/** The condition that would break the day's read. */
export interface ChangeMyMind {
  series?: string;
  text: string;
  threshold?: string;
  horizon?: string;
}

/** The run's SPY forecast, kept for the record. Not drawn by this build. */
export interface SpyForecast {
  scorable?: boolean;
  forecast?: {
    t1Down?: number | null;
    t5Down?: number | null;
    referenceClose?: { date?: string; value?: number };
  };
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
  schedule?: ScheduleItem[];
  policy?: PolicyPath;
  overnight?: string[];
  sections?: Section[];
  coverage?: Section;
  regime?: Section[];
  candidates?: CandidateView[];
  gamma?: GammaProfile[];
  riskList?: Section[];
  decision?: { label: string; value: string }[];
  /** helium emits ONE joined sentence (schema_version 1); the mock guessed an array. Read via `faultList`. */
  degradation?: string | string[];
  /** The helium run id, printed beside the faults it produced. */
  runId?: string;
  /** Supplements only: tracked candidates, dealer-gamma levels, the recap. */
  status?: StatusItem[];
  gex?: GexRow[];
  /** A structure proposed by a supplement, with the reviewer's note. */
  proposal?: CandidateView;
  proposalNote?: string;
  recap?: Section[];
  empty?: boolean;
  charts?: Record<string, unknown>;
  edited?: string;

  /* ---------- v3 ---------- */
  /** The names under watch this period. Weekly and daily both write one. */
  focus?: FocusBlock;
  /** Standing themes and their kill conditions. */
  themes?: Theme[];
  /** Weekly only: the basket table, excess measured against `benchmark`. */
  rotation?: Rotation;
  /** Sources, as-of stamps, and the notes that qualify them. */
  footer?: BriefFooter;
  /**
   * v3's own fault list. Separate from `degradation`, which is one joined
   * sentence about the whole run: these are per-item refusals ("focus TSLA:
   * not on the computed list"). Both are printed, neither replaces the other.
   */
  faults?: string[];
  /** Daily: the one claim, its checks, and what would break it. */
  oneThing?: OneThing;
  checks?: Check[];
  changeMyMind?: ChangeMyMind;
  /** Everything the run saw that did not make the argument. */
  everythingElse?: string[];
  /** Inputs the run used past their freshness, each with how far behind. */
  staleness?: string[];
  spyForecast?: SpyForecast;
  /** "weekly" / "close" — helium's label for the job that wrote this. */
  runLabel?: string;
  /** The base URL helium linked back to. Display-only; argon never follows it. */
  appBase?: string;
  /** Whether the run located a cause for the day's move. Shape not yet fixed. */
  cause?: unknown;
}

/**
 * `null` when this build cannot render the version that arrived.
 *
 * The caller then SAYS which version came and which it understands. A silently
 * blank page is the one outcome a versioned document exists to prevent —
 * that is the whole reason `schema_version` is a column and not a comment.
 */
export function asBriefView(run: AgentRunResponse): BriefView | null {
  if (!SUPPORTED_SCHEMA_VERSIONS.includes(run.schema_version)) return null;
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

/**
 * Every ticker this view is already about.
 *
 * Built from the STRUCTURED fields — the tape, the candidates and their
 * proposal, the gamma and gex rows, the status blocks, the passed-over list —
 * because those are the names the run named on purpose. Prose is never mined
 * for new symbols: that is exactly the guess `lib/flash/tickers.ts` refuses to
 * make. Status and risk titles are ids as often as tickers (`QQQ-2026-09-03-1`
 * is one), so the leading symbol is taken and the rest dropped; a title that
 * is not a symbol contributes nothing.
 */
export function viewTickers(view: BriefView): Set<string> {
  const found: string[] = [];
  // EVERY field here is nullable in practice even where the interface says it
  // is not: this view is helium's document, not argon's object. The close run
  // of 2026-09-03 ships two `riskList` entries with a null `title`, and a bare
  // `.split()` on one of them takes the whole page down.
  const lead = (value: unknown) => String(value ?? "").split(/[-\s]/)[0];
  for (const item of view.tape ?? []) found.push(lead(item?.label));
  for (const c of view.candidates ?? []) found.push(lead(c?.ticker));
  if (view.proposal) found.push(lead(view.proposal.ticker));
  for (const g of view.gamma ?? []) found.push(lead(g?.ticker));
  for (const g of view.gex ?? []) found.push(lead(g?.ticker));
  for (const s of view.status ?? []) found.push(lead(s?.title));
  for (const f of view.focus?.rows ?? []) found.push(lead(f?.ticker));
  for (const r of view.rotation?.rows ?? []) found.push(lead(r?.symbol));
  for (const r of view.riskList ?? []) found.push(lead(r?.title));
  return tickerSet(found);
}

/** Normalize `degradation` so a string, array, or garbage never takes the page down. */
export function faultList(d: unknown): string[] {
  if (typeof d === "string") return d ? [d] : [];
  return Array.isArray(d)
    ? d.filter((x): x is string => typeof x === "string")
    : [];
}
