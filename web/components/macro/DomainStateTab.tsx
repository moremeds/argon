import { DomainStateCard } from "./DomainStateCard";
import { InflationPanels } from "./domain/InflationPanels";
import { UsdPanels } from "./domain/UsdPanels";
import type {
  MacroDomainKey,
  MacroDomainSlot,
  MacroDomainState,
} from "./types";
import { DOMAIN_LABEL, DOMAIN_LEDE } from "./types";

/**
 * One macro domain, as a whole tab.
 *
 * ### What this used to be, and why it changed
 *
 * The first version of this tab was the shared `DomainStateCard` and nothing else,
 * because §1 of the port plan said tabs 00-05 were a _presentation merge_ with no new
 * analytics. That line was superseded on 2026-08-28: the board specifies FOUR panels for
 * inflation and TWO for the dollar, and a conformance audit found zero of the six on the
 * shipped desk (`docs/research/2026-08-28-macro-desk-board-conformance/`). One generic
 * card was not a merge of the board's design; it was the absence of it.
 *
 * What did NOT change is where the numbers come from. The six panels below add no
 * endpoint and no derived quantity that the engine does not publish — the audit's own
 * finding was that the single response each tab already fetched carried every panel.
 * The one arithmetic on this page is the confidence repair table, which is the published
 * multiplication with one published term set to its clear value, and it is tagged
 * `COMPUTED` and shows its formula.
 *
 * The one exception to "one request" is inflation's expectations panel, which cites the
 * rates domain's published breakeven. The board marks that row "(single owner)" for the
 * same reason this cites rather than recomputes it.
 *
 * **The refusal stays, and still earns its place.** A domain on its own page invites two
 * readings the desk does not support — that the number is a verdict about markets, and
 * that it can be put beside the other three and averaged. §9 invariant 1 forbids the
 * second anywhere in the desk's own chrome, and the chain-level claim already has exactly
 * one home: `/api/macro/snapshot`, which is asserted, tested and stored with an explicit
 * ordinal. A tab that quietly implied it would be a second, unversioned copy of that
 * claim.
 */
export function DomainStateTab({
  domain,
  slot,
  citedRates = null,
  citationError,
}: {
  domain: MacroDomainKey;
  slot: MacroDomainSlot;
  /** The rates domain's published state, for tab 03's market-implied leg. */
  citedRates?: MacroDomainState | null;
  citationError?: string;
}) {
  return (
    <div
      data-testid={`macro-domain-tab-${domain}`}
      style={{
        padding: 24,
        maxWidth: 1100,
        margin: "0 auto",
        color: "var(--text-primary)",
      }}
    >
      <header style={{ marginBottom: 18 }}>
        <h1 style={{ margin: 0, fontSize: 20, fontWeight: 600 }}>
          {DOMAIN_LABEL[domain]}
        </h1>
        <p
          style={{
            margin: "6px 0 0",
            fontSize: 13,
            color: "var(--text-secondary)",
            maxWidth: 720,
          }}
        >
          {DOMAIN_LEDE[domain]} One point-in-time state, replayed from the store
          rather than recomputed at read time, carrying the exact observations
          it stood on.
        </p>
      </header>

      <DomainStateCard domain={domain} slot={slot} />

      {/* The board's panels for this domain, below the card that summarises them. Only
          rendered when there is a state to unfold: with no state the card above already
          says which of the two silences it is, and six empty frames beneath it would
          drown that in chrome. Written as two conditions rather than a lookup table —
          the two domains share no panel, so a registry would be one indirection over
          two literals. */}
      {slot.value && domain === "inflation" ? (
        <div style={{ marginTop: 14 }}>
          <InflationPanels
            state={slot.value}
            citedRates={citedRates}
            citationError={citationError}
          />
        </div>
      ) : null}
      {slot.value && domain === "usd" ? (
        <div style={{ marginTop: 14 }}>
          <UsdPanels state={slot.value} />
        </div>
      ) : null}

      <section
        id="refuses"
        data-testid={`macro-domain-refuses-${domain}`}
        aria-label="What this tab refuses"
        style={{
          marginTop: 18,
          padding: "14px 16px",
          background: "var(--bg-panel)",
          border: "1px solid var(--border-dim)",
          borderRadius: 6,
        }}
      >
        <h2
          style={{
            margin: 0,
            fontFamily: "var(--font-mono), monospace",
            fontSize: 10,
            letterSpacing: 1.5,
            textTransform: "uppercase",
            color: "var(--text-muted)",
            fontWeight: 400,
          }}
        >
          What this tab refuses
        </h2>
        <ul
          style={{
            margin: "8px 0 0",
            paddingLeft: 18,
            display: "grid",
            gap: 6,
            fontSize: 12,
            lineHeight: 1.5,
            color: "var(--text-secondary)",
          }}
        >
          <li>
            It is descriptive. The state is what the engine recorded, not
            advice, and it carries no score, allocation or probability of its
            own.
          </li>
          <li>
            It does not combine this domain with the other three. Whether the
            four belong together is a separate, stored claim — the chain verdict
            on the overview — and averaging four differently-grounded answers
            would hide the contradictions listed above rather than resolve them.
          </li>
          <li>
            The tab order on this desk is a reading order, not a causal one.
            Nothing here says this domain causes the next tab.
          </li>
        </ul>
      </section>
    </div>
  );
}
