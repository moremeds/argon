import { BoardPanel, BoardRefusal } from "../domain/BoardPanel";
import { humanizeIdentifier, humanizeText } from "../presentation";
import type {
  MacroDomainKey,
  MacroDomainState,
  MacroOverviewSlot,
} from "../types";
import { CAUSAL_ORDER, DOMAIN_LABEL } from "../types";

/**
 * ANCHOR · THE CHAIN · TODAY — the board's transmission rail.
 *
 * ### Why this is a rail and not the fifth table
 *
 * Four nodes joined by three arrows is the desk's whole thesis rendered as geometry:
 * inflation drives policy, policy drives the dollar, the dollar is one of gold's legs.
 * The board puts it at the ANCHOR of tab 00 rather than the top because it is what the
 * three zones above have been evidence FOR.
 *
 * Adjacency here is the ENGINE's claim about causality, recorded in the store as upstream
 * edges — it is not this component's claim, and no copy on it may say that node N causes
 * node N+1 beyond what those edges assert. The arrows are the board's, drawn between
 * domains the store already orders.
 *
 * ### Still no composite
 *
 * Four nodes on one rail is four answers, not one. There is no summary node at the end,
 * no chain score, no aggregate confidence — a fifth box gathering the four would be the
 * composite this desk exists to refuse, wearing a diagram's clothes.
 */

/** The board's confidence bar: a track, a proportional fill, and the number. The fill
 *  turns warning-coloured below the board's own threshold — the only judgement encoded
 *  here, and it is about the CONFIDENCE, not about the state it qualifies. */
function ConfBar({
  confidence,
}: {
  confidence: string | number | null | undefined;
}) {
  const n = Number(confidence);
  if (!Number.isFinite(n)) {
    return (
      <div className="conf">
        <span>conf</span>
        <div className="track" />
        <span className="num">—</span>
      </div>
    );
  }
  const pct = Math.max(0, Math.min(100, n * 100));
  return (
    <div className="conf">
      <span>conf</span>
      <div className="track">
        <div
          className={n < 0.6 ? "fill low" : "fill"}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="num">{n.toFixed(2)}</span>
    </div>
  );
}

/** Same tone map as `BoardStatePill`, and deliberately almost empty: a state label is not
 *  a verdict. `ON_HOLD` is not "good" and `RISING` is not "bad"; painting them would
 *  encode a house view in a lookup table. */
const STATE_TONE: Record<string, string> = {
  WELL_ABOVE_TARGET: "warnst",
  WELL_BELOW_TARGET: "warnst",
};

/** How many published velocity metrics a node shows. The board draws three; more would
 *  make the four nodes different heights and turn a rail into a ragged column. */
const KV_ROWS = 3;

/**
 * One node.
 *
 * ### Why the testid is `macro-domain-*` and not `macro-chain-node-*`
 *
 * On the board's tab 00 the node IS the domain's card — there is no separate "four states
 * in full" section below the rail, because a second rendering of the same four answers is
 * the wall of cards the zones exist to replace. The established testid moves with the
 * concept rather than being retired alongside a layout, so every invariant written against
 * the old card (three-state, engine version shown, exactly four, no fifth aggregate) keeps
 * testing the thing it was written to protect.
 */
function ChainNode({
  domain,
  slot,
  flag,
}: {
  domain: MacroDomainKey;
  slot: MacroOverviewSlot<MacroDomainState>;
  /** The assembler's finding against THIS domain, if it made one. Rendered on the node so
   *  the chain-verdict panel is not the only place a broken edge is visible. */
  flag?: string;
}) {
  const s = slot.value;

  if (!s) {
    return (
      <div className="node" data-testid={`macro-domain-${domain}`}>
        <h3>{DOMAIN_LABEL[domain]}</h3>
        <span className="state neust" style={{ fontWeight: 400 }}>
          {slot.error ? "request failed" : "never computed"}
        </span>
        <span className="dir">
          {slot.error ??
            "No state has been computed for this domain at this instant — the engine has not run, which is not the same as the request failing."}
        </span>
      </div>
    );
  }

  const velocity = (s.velocity ?? [])
    .filter((v) => !v.unavailable_reason)
    .slice(0, KV_ROWS);

  return (
    <div
      className="node"
      data-testid={`macro-domain-${domain}`}
      data-engine-version={s.engine_version}
    >
      <h3>{DOMAIN_LABEL[domain]}</h3>
      <span className={`state ${STATE_TONE[s.state] ?? "neust"}`} data-raw-value={s.state}>
        {humanizeIdentifier(s.state)}
      </span>
      <span className="dir" data-raw-value={s.direction}>
        {humanizeIdentifier(s.direction)}
      </span>
      {flag ? (
        <span
          className="dir"
          data-testid={`macro-chain-flag-${domain}`}
          style={{ color: "var(--warning)" }}
        >
          {humanizeText(flag)}
        </span>
      ) : null}
      <ConfBar confidence={s.confidence} />
      {/* The evidence count sits ABOVE the velocity rows for the same reason the card it
          replaces carried one: a state is a conclusion, and a conclusion shown without the
          size of what it stood on invites being read as an opinion. */}
      <div className="kv" data-testid={`macro-evidence-count-${domain}`}>
        <span>evidence cited</span>
        <span className="num">{(s.evidence ?? []).length}</span>
      </div>
      {velocity.map((v) => {
        const n = Number(v.value);
        const signed = Number.isFinite(n) ? n : null;
        return (
          <div className="kv" key={v.metric}>
            <span title={v.metric} data-raw-value={v.metric}>{humanizeIdentifier(v.metric)}</span>
            <span
              className={`num ${
                signed === null
                  ? ""
                  : signed > 0
                    ? "delta-up"
                    : signed < 0
                      ? "delta-dn"
                      : "delta-flat"
              }`}
            >
              {signed === null ? "—" : signed.toFixed(2)}
              {v.unit ? ` ${humanizeIdentifier(v.unit)}` : ""}
            </span>
          </div>
        );
      })}
      {velocity.length === 0 ? (
        <div className="kv">
          <span>velocity</span>
          <span className="num">none published</span>
        </div>
      ) : null}
    </div>
  );
}

export function ChainRail({
  domains,
  reasons = [],
}: {
  domains: Record<MacroDomainKey, MacroOverviewSlot<MacroDomainState>>;
  /** The assembler's per-domain findings, so an offending node can be marked. Defaulted
   *  to empty rather than required: a rail with no snapshot is still a rail. */
  reasons?: readonly { domain: string; detail: string }[];
}) {
  const answered = CAUSAL_ORDER.filter((d) => domains[d].value !== null);
  const flagged = new Map(reasons.map((r) => [r.domain, r.detail]));

  return (
    <>
      {/* Nodes and arrows are INTERLEAVED as siblings, because the board's grid is
          `1fr 28px 1fr 28px 1fr 28px 1fr` — the arrows occupy their own columns rather
          than sitting inside a node. Wrapping each pair would collapse seven tracks into
          four and the arrows would lose their fixed width. */}
      <div className="chain" data-testid="macro-chain-rail">
        {CAUSAL_ORDER.flatMap((domain, i) => [
          <ChainNode
            key={domain}
            domain={domain}
            slot={domains[domain]}
            flag={flagged.get(domain)}
          />,
          ...(i < CAUSAL_ORDER.length - 1
            ? [
                <div className="arrow" key={`arrow-${domain}`} aria-hidden>
                  →
                </div>,
              ]
            : []),
        ])}
      </div>
      <div className="edge-note">
        {answered.length} of {CAUSAL_ORDER.length} nodes answered at this
        instant · the arrows are the store&rsquo;s own causal order, not a
        correlation measured here
      </div>
    </>
  );
}

/**
 * PANEL 10 · Off-chain dimension · Energy (proposal).
 *
 * The board's `.ghost` — dashed and transparent so it cannot be mistaken for a reading.
 * Everything inside is explicitly not a measurement: there is no energy domain, no energy
 * engine and no energy state.
 *
 * `PLANNED` is the right basis and the reason the tag vocabulary has three values: this is
 * prose describing what WOULD be measured. A `COMPUTED` tag here would claim arithmetic
 * happened.
 */
export function EnergyProposalPanel() {
  return (
    <BoardPanel
      id="energy-proposal"
      title="Energy input · planned"
      questions={["Q6"]}
      basis="PLANNED"
      sourceLabel="Absent path"
      source={
        <>
          no energy domain, engine or state exists · the macro store holds zero
          energy series, so there is nothing here to read and nothing to go
          stale
        </>
      }
    >
      <div className="ghost" data-testid="macro-energy-ghost">
        <h3>Energy → Inflation</h3>
        <span>
          WTI, Brent and seasonal natural gas belong <b>upstream of inflation</b>.
        </span>
        <span>
          No state is shown until the inputs and thresholds exist.
        </span>
      </div>
    </BoardPanel>
  );
}

/**
 * PANEL 11 · Boundary · what is NOT on this desk.
 *
 * The board closes tab 00 with a refusal, and it is the panel most worth keeping honest:
 * everything listed is something the desk could plausibly be expected to do and
 * deliberately does not. The list is deliberately brief — a boundary naming twenty things
 * is a disclaimer, not a boundary.
 */
export function BoundaryPanel() {
  return (
    <BoardPanel
      id="boundary"
      title="Desk limits"
      questions={["Q7"]}
      basis="PLANNED"
      sourceLabel="Policy"
      source={<>the desk&rsquo;s own standing rules, not a data limitation</>}
    >
      <BoardRefusal kind="REFUSAL" testId="macro-boundary-refusal">
        No composite score, re-ranking, directional stance or forecast. Each
        domain keeps its own publisher, unit and confidence.
      </BoardRefusal>
    </BoardPanel>
  );
}
