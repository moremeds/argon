import type { MacroContextSnapshot, MacroSnapshotReason } from "./types";
import { STATUS_LEDE } from "./types";

/**
 * The chain-level verdict, rendered beside the cards rather than instead of them.
 *
 * Four individually-fresh cards cannot show that USD stood on last night's rates — every
 * row they fetch is current and individually honest, and nothing about a timestamp gives
 * it away. Only the snapshot carries the claim that the four belong together, and it
 * decides that from dependency-edge identity: does the upstream state id a domain
 * actually cited equal the one the snapshot holds for that domain.
 *
 * It reports and does not withhold. The authority boundary for this layer is
 * risk-monitoring: it may say the chain is broken and where, and it may not decide for
 * the reader that the individual answers are no longer worth seeing.
 */
export function ChainRefusal({
  snapshot,
}: {
  snapshot: MacroContextSnapshot | null;
}) {
  if (snapshot === null) {
    return (
      <div
        data-testid="macro-chain-unassembled"
        style={{ ...BOX, borderColor: "var(--border-subtle)" }}
      >
        <strong style={LABEL}>Chain never assembled</strong>
        <p style={BODY}>
          No context snapshot has been assembled for this instant, so the four cards below
          are four independent reads. That is not the same as a coherent chain — nothing
          has checked whether they belong together.
        </p>
      </div>
    );
  }

  if (snapshot.status === "complete") return null;

  return (
    <div
      data-testid="macro-chain-refusal"
      data-status={snapshot.status}
      style={{ ...BOX, borderColor: "var(--danger, #a33)" }}
    >
      <strong style={LABEL}>
        Chain {snapshot.status} — read the cards below separately, not as a chain
      </strong>
      <p style={BODY}>{STATUS_LEDE[snapshot.status]}</p>
      <ul style={{ margin: "8px 0 0", paddingLeft: 18, fontSize: 12.5 }}>
        {(snapshot.reasons ?? []).map((reason: MacroSnapshotReason) => (
          <li key={`${reason.domain}-${reason.kind}`} style={{ marginBottom: 3 }}>
            <code style={{ color: "var(--text-primary)" }}>{reason.domain}</code>{" "}
            <span style={{ color: "var(--text-muted)" }}>({reason.kind})</span> —{" "}
            {reason.detail}
          </li>
        ))}
      </ul>
      <p style={{ ...BODY, marginTop: 8, color: "var(--text-muted)" }}>
        Assembled {snapshot.assembled_at} by {snapshot.assembler_version}. The snapshot
        holds what each domain actually cited; it never swaps in a fresher upstream to make
        the chain look coherent.
      </p>
    </div>
  );
}

const BOX = {
  border: "1px solid",
  borderRadius: 6,
  padding: "10px 12px",
  marginBottom: 14,
  background: "var(--bg-elevated, rgba(255,255,255,0.02))",
} as const;

const LABEL = { fontSize: 13, display: "block" } as const;

const BODY = {
  margin: "4px 0 0",
  fontSize: 12.5,
  color: "var(--text-secondary)",
} as const;
