import type { ReactNode } from "react";

import { BoardPanel } from "@/components/macro/domain/BoardPanel";
import type { components } from "@/lib/types";

import { CorrelationHistoryPanel } from "./correlation/CorrelationHistoryPanel";
import { ExpressionCostPanel } from "./ExpressionCostPanel";
import { InputManifestPanel } from "./InputManifestPanel";
import { GoldCompassHeader } from "./GoldCompassHeader";
import { CyclicalPanel } from "./lens2/CyclicalPanel";
import { CbReservesPanel } from "./lens1/CbReservesPanel";
import { StructuralPanel } from "./lens1/StructuralPanel";
import { ThreeLensesPanel } from "./ThreeLensesPanel";
import { TransmissionGaugePanel } from "./TransmissionGaugePanel";

type State = components["schemas"]["GoldStateResponse"];
type GaugePoint = components["schemas"]["GoldGaugeTimeSeriesPoint"];

type Props = {
  state: State;
  replayDate?: string;
  /** Forwarded to the header. The macro desk's gold tab sets it `false`: that tab already
   *  carries `ReplayControl`, and this header's picker navigates away from the desk. */
  showReplayPicker?: boolean;
  /**
   * The board's `.sec-title` + `.sec-sub`, supplied by the macro desk's gold tab.
   *
   * Absent on `/gold/replay/<date>`, which has no tab bar to be titled under and so keeps
   * the Gold Compass lockup. The BODY below is now identical on both routes — see the
   * block above the component.
   */
  deskHeading?: ReactNode;
  /**
   * `/api/gold/gauge` `history_252d`, for the anchor-decay panel.
   *
   * Optional because only ONE of this component's two routes can supply it. The macro
   * desk's live gold tab fetches it beside the posture; `/gold/replay/<date>` cannot,
   * because the gauge route takes no date and answering a replayed observation with the
   * live anchor history would date-mismatch the one panel whose subject is time. Absent,
   * the panel draws the sparse pairs and says which request it did not make.
   */
  anchorHistory?: GaugePoint[] | null;
};

/**
 * Board tab 05, in the board's own layout.
 *
 * ### What changed, and why the previous shape was wrong
 *
 * This used to be nine full-width bands separated by hairlines, each holding a house-styled
 * panel with its own mono heading. Every lens was present and correctly bound — the
 * conformance audit found the tab content-complete — and it still looked nothing like the
 * board, because the board's t5 is a GRID of framed panels: two pairs, then a row of three,
 * then the manifest across the full measure. A stack of full-width bands makes eight
 * panels of equal weight and forces the reader down a column; the board's grid puts the
 * gauge beside the lenses it governs, and the anchor beside what the anchor costs.
 *
 * The earlier note here said gold "keeps its own visual idiom rather than borrowing the
 * macro panel frame". That was the divergence: the desk read as two products sharing a tab
 * bar. The frame is the shared grammar, so gold wears it.
 *
 * ### One design, both routes
 *
 * `board.css` is scoped to `.board` and was imported only by `app/macro/layout.tsx`, which
 * is why gold carried an inline copy of the board's read-rail. `/gold/replay/<date>` now
 * imports the stylesheet and renders inside `.board` too, so there is one design and the
 * copy is deleted. The heading is the only thing that still differs between the routes,
 * because only one of them sits under a tab bar.
 */
export function GoldCompassLayout({
  state,
  replayDate,
  showReplayPicker,
  deskHeading,
  anchorHistory,
}: Props) {
  const suspended = state.gauge.state === "suspended";

  return (
    <>
      {deskHeading ?? (
        <GoldCompassHeader
          obsDate={replayDate ?? state.obs_date}
          showReplayPicker={showReplayPicker}
        />
      )}

      {/* The gauge opens the tab and sits BESIDE the lenses it governs, which is the whole
          argument for the board's pairing: when it reads suspended the cyclical lens is
          dimmed, and a reader should not have to scroll to discover the condition that
          decides how to read what follows. */}
      <div className="grid g2">
        <TransmissionGaugePanel gauge={state.gauge} />
        <ThreeLensesPanel state={state} />
      </div>

      <div className="grid g2" style={{ marginTop: 12 }}>
        <CorrelationHistoryPanel
          history={state.correlation_history}
          anchorHistory={anchorHistory}
        />
        <ExpressionCostPanel structural={state.structural} />
      </div>

      {/* The board splits lens 1 in two — official-sector accumulation and western
          institutional flow are different behaviours with different reads, and the single
          merged panel promoted the strategic bucket to a headline while the other two rode
          a sub-line. The dimmed cyclical panel is the third column, which is where the
          board puts it: adjacent to the flows, not below them. */}
      <div className="grid g3" style={{ marginTop: 12 }}>
        <CbReservesPanel structural={state.structural} />
        <StructuralPanel structural={state.structural} />
        <CyclicalPanel cyclical={state.cyclical} dimmed={suspended} />
      </div>

      {/* Full measure, and a panel rather than the footer this was: a manifest that named
          only the inputs it managed to read presented a partial audit trail as a complete
          one. */}
      <div className="grid" style={{ marginTop: 12 }}>
        <InputManifestPanel
          obsDate={state.obs_date}
          computedAt={state.computed_at}
          inputsUsed={state.inputs_used}
        />
      </div>
    </>
  );
}

/** Re-exported so the panels below can wear the board frame without each importing across
 *  subtrees. `components/gold` -> `components/macro/domain` is the direction the port
 *  allows; the reverse (macro reaching into a domain subtree) is what §7 forbids. */
export { BoardPanel };
