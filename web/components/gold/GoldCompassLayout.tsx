import type { components } from "@/lib/types";

import { CorrelationHistoryPanel } from "./correlation/CorrelationHistoryPanel";
import { DataAuditFooter } from "./DataAuditFooter";
import { ExpressionCostPanel } from "./ExpressionCostPanel";
import { GoldCompassHeader } from "./GoldCompassHeader";
import { KpiStrip } from "./kpi/KpiStrip";
import { CyclicalPanel } from "./lens2/CyclicalPanel";
import { StructuralPanel } from "./lens1/StructuralPanel";
import { ValuationPanel } from "./lens3/ValuationPanel";
import { TransmissionGaugePanel } from "./TransmissionGaugePanel";

type State = components["schemas"]["GoldStateResponse"];

const sectionStyle: React.CSSProperties = {
  padding: "20px 24px",
  borderBottom: "1px solid var(--border-dim, #1b2030)",
};

type Props = {
  state: State;
  replayDate?: string;
  /** Forwarded to the header. The macro desk's gold tab sets it `false`: that tab already
   *  carries `ReplayControl`, and this header's picker navigates away from the desk. */
  showReplayPicker?: boolean;
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
}: Props) {
  return (
    <main style={{ background: "var(--bg-base, #060810)", minHeight: "100vh" }}>
      <GoldCompassHeader
        obsDate={replayDate ?? state.obs_date}
        showReplayPicker={showReplayPicker}
      />

      {/* The board's opening panel. It governs the two lenses below it -- when the
          gauge is suspended the cyclical band is dimmed -- so it is stated before them
          rather than discovered inside a KPI row. */}
      <section
        role="region"
        aria-label="Transmission gauge"
        data-questions="Q4 Q7"
        style={sectionStyle}
      >
        <TransmissionGaugePanel gauge={state.gauge} />
      </section>

      <section
        role="region"
        aria-label="KPI strip"
        data-questions="Q1"
        style={sectionStyle}
      >
        <KpiStrip state={state} />
      </section>

      <section
        role="region"
        aria-label="Lens 1 structural flow"
        data-questions="Q5"
        style={sectionStyle}
      >
        <StructuralPanel structural={state.structural} />
      </section>

      <section
        role="region"
        aria-label="Expression cost"
        data-questions="Q2"
        style={sectionStyle}
      >
        <ExpressionCostPanel structural={state.structural} />
      </section>

      <section
        role="region"
        aria-label="Lens 2 cyclical posture"
        data-questions="Q1"
        style={{
          ...sectionStyle,
          opacity: state.gauge.state === "suspended" ? 0.7 : 1,
        }}
      >
        <CyclicalPanel cyclical={state.cyclical} />
      </section>

      <section
        role="region"
        aria-label="Lens 3 valuation overlay"
        data-questions="Q1"
        style={sectionStyle}
      >
        <ValuationPanel valuation={state.valuation} />
      </section>

      {/* The lens-decomposition panel used to sit beside this one. It read
          ``state.decomposition_rows``, which the producer leaves empty on every
          run (see reports/gold_posture.py), so it only ever drew its own empty
          state. The field stays on the API contract; the render is gone. */}
      <section
        role="region"
        aria-label="Correlation history"
        data-questions="Q4"
        style={sectionStyle}
      >
        <CorrelationHistoryPanel history={state.correlation_history} />
      </section>

      <DataAuditFooter
        obsDate={state.obs_date}
        computedAt={state.computed_at}
        inputsUsed={state.inputs_used}
      />
    </main>
  );
}
