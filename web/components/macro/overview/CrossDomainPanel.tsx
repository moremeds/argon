import { ChainRefusal } from "../ChainRefusal";
import { instantUtc } from "../format";
import type { MacroContextSnapshot, MacroOverviewSlot } from "../types";
import { MONO_LABEL, Panel } from "./Panel";

/**
 * Contradictions BETWEEN domains — the one question no card can answer about itself.
 *
 * Four individually-fresh cards cannot show that USD stood on last night's rates: every
 * row they fetch is current and individually honest, and nothing about a timestamp gives
 * it away. Only `/api/macro/snapshot` carries the claim that the four belong together, and
 * it decides that from dependency-edge IDENTITY — does the upstream `state_id` a domain
 * actually cited equal the one this snapshot holds (`macro/snapshot.py:15-21`).
 *
 * The refusal itself is `ChainRefusal`, unchanged and shared with the four-card view below
 * it. What this panel adds is the `complete` case, which `ChainRefusal` renders as nothing
 * — correct beside cards, wrong on an overview whose subject IS the chain: a panel titled
 * "cross-domain contradictions" that renders empty is indistinguishable from one that
 * failed to load.
 *
 * The affirmative sentence is deliberately narrow, and it is the router's own
 * (`api/routers/macro.py`): a `complete` status is not a claim that the macro picture is
 * right, only that the chain is internally coherent. Widening it into "the macro picture
 * holds together" would be the desk taking a view, which is exactly what four separately
 * grounded states exist to refuse.
 */
export function CrossDomainPanel({
  snapshot,
}: {
  snapshot: MacroOverviewSlot<MacroContextSnapshot>;
}) {
  const value = snapshot.value;
  return (
    <Panel
      id="cross-domain"
      title="Cross-domain contradictions"
      lede="The assembler's verdict on whether the four answers above belong together, read from /api/macro/snapshot beside the cards rather than instead of them. It reports and never repairs: a snapshot may not substitute a fresher upstream to make a chain look coherent."
    >
      <ChainRefusal snapshot={value} error={snapshot.error} />

      {value && value.status === "complete" ? (
        <div data-testid="macro-chain-coherent">
          <p style={{ margin: 0, fontSize: 12.5, color: "var(--text-secondary)", lineHeight: 1.55 }}>
            No cross-domain contradiction. Every downstream state below cited the upstream
            answer this snapshot holds, checked by state identity rather than by how fresh
            the rows look.{" "}
            <strong>
              That is not a claim that the macro picture is right — only that the chain is
              internally coherent.
            </strong>{" "}
            The four states remain descriptive, and a coherent chain of descriptive answers
            is still four descriptions.
          </p>
          <p style={{ ...MONO_LABEL, margin: "10px 0 0" }}>
            assembled {instantUtc(value.assembled_at)} · {value.assembler_version} ·
            answers for {instantUtc(value.as_of)}
          </p>
        </div>
      ) : null}
    </Panel>
  );
}
