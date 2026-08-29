import type { ReactNode } from "react";

import type { components } from "@/lib/types";

import { CorrelationHistoryPanel } from "./correlation/CorrelationHistoryPanel";
import { ExpressionCostPanel } from "./ExpressionCostPanel";
import { InputManifestPanel } from "./InputManifestPanel";
import { GoldCompassHeader } from "./GoldCompassHeader";
import { KpiStrip } from "./kpi/KpiStrip";
import { CyclicalPanel } from "./lens2/CyclicalPanel";
import { CbReservesPanel } from "./lens1/CbReservesPanel";
import { StructuralPanel } from "./lens1/StructuralPanel";
import { ValuationPanel } from "./lens3/ValuationPanel";
import { TransmissionGaugePanel } from "./TransmissionGaugePanel";

type State = components["schemas"]["GoldStateResponse"];
type GaugePoint = components["schemas"]["GoldGaugeTimeSeriesPoint"];

/**
 * Two chromes, one body.
 *
 * On the macro desk this is board tab 05, and the board separates its bands with
 * whitespace, not rules: a full-width hairline between every section was the loudest line
 * on the tab, drawn between panels that already carry their own borders. The desk chrome
 * also drops the horizontal padding, because the `.board` wrapper around it owns the
 * column — keeping both would inset gold from the measure every other tab sits on.
 *
 * On the standalone `/gold/replay/<date>` route there is no `.board` wrapper and no tab
 * bar, so the banded chrome and its own padding stay.
 */
const sectionStyle: React.CSSProperties = {
  padding: "20px 24px",
  borderBottom: "1px solid var(--border-dim, #1b2030)",
};

const deskSectionStyle: React.CSSProperties = {
  padding: "0 0 22px",
};

type Props = {
  state: State;
  replayDate?: string;
  /** Forwarded to the header. The macro desk's gold tab sets it `false`: that tab already
   *  carries `ReplayControl`, and this header's picker navigates away from the desk. */
  showReplayPicker?: boolean;
  /**
   * The board's `.sec-title` + `.sec-sub`, supplied by the macro desk's gold tab.
   *
   * Its presence is what selects the desk chrome — one prop rather than a `variant` flag
   * beside it, because there is exactly one decision here and two props would let a
   * caller ask for board bands under a Gold Compass lockup.
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
 * Reordered on 2026-08-28 to the board's own tab-05 sequence.
 *
 * The conformance audit found this tab content-complete and wrongly framed: every lens
 * was present, and the question that governs how to read them — is the real-rate channel
 * transmitting at all — was one tile in a five-tile strip. The board opens the tab on it.
 * So does this now.
 *
 * `data-questions` on each band is the board's acceptance test, carried onto a subtree
 * that does not use `BoardPanel`. Gold keeps its own visual idiom (mono section headings
 * on banded rows) rather than borrowing the macro panel frame, but a section that answers
 * none of Q1-Q7 should be as visible here as anywhere.
 */
export function GoldCompassLayout({
  state,
  replayDate,
  showReplayPicker,
  deskHeading,
  anchorHistory,
}: Props) {
  const onDesk = deskHeading != null;
  const band = onDesk ? deskSectionStyle : sectionStyle;
  return (
    <main style={{ background: "var(--bg-base, #060810)", minHeight: "100vh" }}>
      {onDesk ? (
        deskHeading
      ) : (
        <GoldCompassHeader
          obsDate={replayDate ?? state.obs_date}
          showReplayPicker={showReplayPicker}
        />
      )}

      {/* The board's opening panel. It governs the two lenses below it -- when the
          gauge is suspended the cyclical band is dimmed -- so it is stated before them
          rather than discovered inside a KPI row. */}
      <section
        role="region"
        aria-label="Transmission gauge"
        data-questions="Q4 Q7"
        style={band}
      >
        <TransmissionGaugePanel gauge={state.gauge} />
      </section>

      <section
        role="region"
        aria-label="KPI strip"
        data-questions="Q1"
        style={band}
      >
        <KpiStrip state={state} />
      </section>

      {/* The board splits lens 1 in two — official-sector accumulation and western
          institutional flow are different behaviours with different reads, and the
          single merged panel promoted the strategic bucket to a headline while the
          other two rode a sub-line. Order follows the board: central banks first. */}
      <section
        role="region"
        aria-label="Central banks"
        data-questions="Q5"
        style={band}
      >
        <CbReservesPanel structural={state.structural} />
      </section>

      <section
        role="region"
        aria-label="Western institutional flows"
        data-questions="Q5"
        style={band}
      >
        <StructuralPanel structural={state.structural} />
      </section>

      <section
        role="region"
        aria-label="Expression cost"
        data-questions="Q2"
        style={band}
      >
        <ExpressionCostPanel structural={state.structural} />
      </section>

      <section
        role="region"
        aria-label="Lens 2 cyclical posture"
        data-questions="Q1"
        style={{
          ...band,
          opacity: state.gauge.state === "suspended" ? 0.7 : 1,
        }}
      >
        <CyclicalPanel cyclical={state.cyclical} />
      </section>

      <section
        role="region"
        aria-label="Lens 3 valuation overlay"
        data-questions="Q1"
        style={band}
      >
        <ValuationPanel valuation={state.valuation} />
      </section>

      {/* The lens-decomposition panel used to sit beside this one. It read
          ``state.decomposition_rows``, which the producer leaves empty on every
          run (see reports/gold_posture.py), so it only ever drew its own empty
          state. The field stays on the API contract; the render is gone. */}
      <section
        role="region"
        aria-label="Anchor decay"
        data-questions="Q4"
        style={band}
      >
        <CorrelationHistoryPanel
          history={state.correlation_history}
          anchorHistory={anchorHistory}
        />
      </section>

      {/* The board's closing panel, and a panel rather than the footer this was: a
          manifest that named only the inputs it managed to read presented a partial
          audit trail as a complete one. */}
      <section
        role="region"
        aria-label="Input manifest"
        data-questions="Q7"
        style={band}
      >
        <InputManifestPanel
          obsDate={state.obs_date}
          computedAt={state.computed_at}
          inputsUsed={state.inputs_used}
        />
      </section>
    </main>
  );
}
