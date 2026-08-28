import { DomainStateCard } from "./DomainStateCard";
import type { MacroDomainKey, MacroDomainSlot } from "./types";
import { DOMAIN_LABEL, DOMAIN_LEDE } from "./types";

/**
 * One macro domain, as a whole tab.
 *
 * Tabs 03 (inflation) and 04 (USD) are a PRESENTATION MERGE and nothing else — §1 of the
 * port plan rules out new analytics for tabs 00-05, and §3's binding table gives each of
 * these exactly one request. So the body is `DomainStateCard`, unchanged: the same
 * component `/macro` already renders for these two domains, showing the same stored
 * answer, the same confidence terms, the same contradictions and the same cited evidence.
 * Nothing here recomputes, re-ranks or re-weights any of it.
 *
 * What the tab adds over the card is a frame the card cannot carry when it is one of four
 * in a column: a heading, and a refusal. Both are prose.
 *
 * **The refusal is the part that earns its place.** A domain on its own page invites two
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
}: {
  domain: MacroDomainKey;
  slot: MacroDomainSlot;
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
