import { BoardPanel } from "@/components/macro/domain/BoardPanel";
import type { components } from "@/lib/types";

import { PersistOnlyBadge } from "./chips/PersistOnlyBadge";

type S = components["schemas"]["GoldStructuralPostureModel"];

/**
 * Board t5 · "Expression cost · what the option market charges".
 *
 * Promoted out of the lens-1 card grid on 2026-08-28. It was a sixth tile among five
 * flow readings, which put it in the wrong company: the other five answer WHO IS BUYING,
 * and this one answers WHAT IT COSTS TO TAKE THE VIEW. Those are different questions and
 * the board gives the second its own panel.
 *
 * It keeps its `persist-only` badge and gains no interpretation. The skew is captured and
 * stored; no model on this desk consumes it, so the panel reports the charge and says
 * nothing about what to do with it.
 */
export function ExpressionCostPanel({ structural }: { structural: S }) {
  const raw = structural.uw_25d_skew_sigma;
  const n = raw === null || raw === undefined ? NaN : Number(raw);

  return (
    <BoardPanel
      id="expression-cost"
      title="Expression cost"
      questions={["Q2", "Q7"]}
      basis="REAL"
      source={
        <>
          /api/gold/state structural.uw_25d_skew_sigma · captured and stored; no
          model on this desk consumes it
        </>
      }
    >
      {/* The board's `.big` — one headline number, because the panel answers one
          question. Two decimals, not the stored precision: the raw field is a
          full-precision decimal string and interpolating it printed sixteen significant
          figures against a "sigma" suffix, a claim of measurement precision the reading
          does not have. */}
      <div className="big num">
        {Number.isFinite(n) ? `${n.toFixed(2)}σ` : "—"}{" "}
        <small>UW 25Δ skew</small>
      </div>
      <div>
        <PersistOnlyBadge />
      </div>

      <p className="read">
        {Number.isFinite(n) ? (
          <>
            25-delta skew versus its own history; this is the current cost of
            expressing a directional view.
          </>
        ) : (
          <>
            No skew was captured for this observation date.
          </>
        )}{" "}
        Stored for context; it does not drive posture.
      </p>
    </BoardPanel>
  );
}
