import { ChainRefusal } from "./ChainRefusal";
import { DomainStateCard } from "./DomainStateCard";
import type {
  MacroContextSnapshot,
  MacroDomainKey,
  MacroDomainSlot,
} from "./types";
import { CAUSAL_ORDER, DOMAIN_LABEL } from "./types";

/**
 * The four macro domain states, rendered as a chain rather than a scoreboard.
 *
 * There is deliberately no composite here, and there will not be one: each engine publishes
 * its own state, direction and confidence, and averaging four differently-grounded answers
 * into a single number would hide exactly the disagreements the contradiction lists exist to
 * show.  The page's job is to make the causal order legible, not to collapse it.
 */
export function MacroDesk({
  domains,
  snapshot = null,
}: {
  domains: Record<string, MacroDomainSlot>;
  /** The chain-level verdict. ``null`` means none was ever assembled, which is NOT the
   *  same as a coherent chain and must never render as one. */
  snapshot?: MacroContextSnapshot | null;
}) {
  const refusedBy = new Map(
    (snapshot?.reasons ?? []).map((reason) => [reason.domain, reason]),
  );
  return (
    <div
      style={{
        padding: 24,
        maxWidth: 1100,
        margin: "0 auto",
        color: "var(--text-primary)",
      }}
    >
      <header style={{ marginBottom: 18 }}>
        <h1 style={{ margin: 0, fontSize: 20, fontWeight: 600 }}>Macro Context</h1>
        <p
          style={{
            margin: "6px 0 0",
            fontSize: 13,
            color: "var(--text-secondary)",
            maxWidth: 720,
          }}
        >
          Four point-in-time domain states in causal order. Each is a stored answer replayed,
          never recomputed at read time, and each carries the exact observations it stood on.
          Descriptive only — these states do not rank, size, or recommend anything.
        </p>
      </header>

      <ChainRefusal snapshot={snapshot} />

      <div style={{ display: "grid", gap: 10 }}>
        {CAUSAL_ORDER.map((domain: MacroDomainKey, i) => (
          <div key={domain} style={{ display: "grid", gap: 10 }}>
            <div style={{ display: "grid", gap: 6 }}>
              {refusedBy.has(domain) ? (
                <div
                  data-testid={`macro-chain-flag-${domain}`}
                  style={{
                    fontSize: 12,
                    color: "var(--danger, #a33)",
                    padding: "2px 2px 0",
                  }}
                >
                  {/* Prefixed with the domain: the flag sits between two cards, and
                      without a name it reads as belonging to the one above it. */}
                  <strong>{DOMAIN_LABEL[domain]}:</strong>{" "}
                  {refusedBy.get(domain)?.detail}
                </div>
              ) : null}
              <DomainStateCard
                domain={domain}
                slot={domains[domain] ?? { value: null }}
              />
            </div>
            {i < CAUSAL_ORDER.length - 1 ? (
              <div
                aria-hidden
                style={{
                  justifySelf: "center",
                  color: "var(--text-muted)",
                  fontSize: 14,
                  lineHeight: 1,
                }}
              >
                ↓
              </div>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}
