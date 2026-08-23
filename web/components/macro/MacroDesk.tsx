import { DomainStateCard } from "./DomainStateCard";
import type { MacroDomainKey, MacroDomainSlot } from "./types";
import { CAUSAL_ORDER } from "./types";

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
}: {
  domains: Record<string, MacroDomainSlot>;
}) {
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

      <div style={{ display: "grid", gap: 10 }}>
        {CAUSAL_ORDER.map((domain: MacroDomainKey, i) => (
          <div key={domain} style={{ display: "grid", gap: 10 }}>
            <DomainStateCard
              domain={domain}
              slot={domains[domain] ?? { value: null }}
            />
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
