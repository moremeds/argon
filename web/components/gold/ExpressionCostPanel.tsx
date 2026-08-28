import type { components } from "@/lib/types";

import { Tile } from "./Tile";
import { PersistOnlyBadge } from "./chips/PersistOnlyBadge";
import { goldReadStyle } from "./readStyle";

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
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <h2
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 12,
          letterSpacing: 1.8,
          textTransform: "uppercase",
          color: "var(--text-primary, #cfd2db)",
          margin: 0,
        }}
      >
        EXPRESSION COST · WHAT THE OPTION MARKET CHARGES
      </h2>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(200px, 240px))",
          gap: 12,
        }}
      >
        <Tile
          label="UW 25Δ SKEW"
          // Two decimals, not the stored precision. The raw field is a full-precision
          // decimal string and interpolating it printed sixteen significant figures
          // against a "sigma" suffix -- a claim of measurement precision the reading
          // does not have.
          value={Number.isFinite(n) ? `${n.toFixed(2)}σ` : "—"}
          sub={<PersistOnlyBadge />}
        />
      </div>

      <p style={goldReadStyle}>
        {Number.isFinite(n) ? (
          <>
            The 25-delta skew, in standard deviations of its own history. It
            says what the option market is charging to express a directional
            view in gold right now, which is a different question from the flow
            readings above — those say who is buying, this says what buying
            costs.
          </>
        ) : (
          <>
            No skew reading was captured for this observation date, so what the
            option market is charging is unknown here rather than neutral.
          </>
        )}{" "}
        It is stored and displayed; nothing on this desk consumes it, so it
        carries no posture of its own.
      </p>
    </div>
  );
}
