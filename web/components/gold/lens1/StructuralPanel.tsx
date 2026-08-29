import { BoardPanel } from "@/components/macro/domain/BoardPanel";
import type { components } from "@/lib/types";

import { PostureChip, type PostureState } from "../chips/PostureChip";

import { ComexRegimeCard } from "./ComexRegimeCard";
import { CotPositioningCard } from "./CotPositioningCard";
import { EtfFlowCard } from "./EtfFlowCard";
import { FxBasketCard } from "./FxBasketCard";
import { LbmaMomentumCard } from "./LbmaMomentumCard";
import { StructuralPostureText } from "./StructuralPostureText";

type S = components["schemas"]["GoldStructuralPostureModel"];

/**
 * Board t5 — "Western institutional flows · L1 detail" (Q5).
 *
 * Lens 1 answers WHO IS BUYING, and the board splits that answer in two: official-sector
 * accumulation is one behaviour and western institutional flow is another, so they are
 * separate panels with separate reads. Two tiles left this grid for that reason:
 *
 * - The CB reserves tile and the holdings-vs-price chart moved to `CbReservesPanel` on
 *   2026-08-29, where the three buckets get equal weight instead of one headline and a
 *   run-on sub-line.
 * - The 25-delta skew tile left on 2026-08-28 for `ExpressionCostPanel` — these cards say
 *   who is buying, and the skew says what it costs to take the view.
 *
 * `LbmaMomentumCard` arrived in the same pass. The board carries an LBMA row here and the
 * field was on every response, rendered by nothing.
 *
 * The posture chip and state label stay on this panel rather than moving with the chart:
 * `state_label` and `posture_chip` are lens-1 wide, and duplicating them onto both halves
 * would show one lens publishing two postures.
 */
export function StructuralPanel({ structural }: { structural: S }) {
  return (
    <BoardPanel
      id="structural-flows"
      title="Institutional flows"
      questions={["Q5"]}
      basis="REAL"
      source={
        <>
          /api/gold/state structural · ETF holdings, LBMA, COMEX, CFTC COT and
          the FX basket, each as its own source published it
        </>
      }
    >
      {/* The posture chip and state label stay on THIS half of lens 1 rather than moving
          with the central-bank chart: `state_label` and `posture_chip` are lens-1 wide,
          and duplicating them onto both panels would show one lens publishing two
          postures. */}
      <div className="lgd">
        <PostureChip
          state={(structural.posture_chip ?? "NEUTRAL") as PostureState}
        />
        <span className="dir">{structural.state_label ?? "—"}</span>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
          gap: 8,
        }}
      >
        <EtfFlowCard structural={structural} />
        <LbmaMomentumCard structural={structural} />
        <ComexRegimeCard structural={structural} />
        <CotPositioningCard structural={structural} />
        <FxBasketCard structural={structural} />
      </div>

      <StructuralPostureText structural={structural} />
    </BoardPanel>
  );
}
