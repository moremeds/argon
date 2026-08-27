import type { components } from "@/lib/types";

import { CorrelationHistoryPanel } from "./correlation/CorrelationHistoryPanel";
import { DataAuditFooter } from "./DataAuditFooter";
import { GoldCompassHeader } from "./GoldCompassHeader";
import { KpiStrip } from "./kpi/KpiStrip";
import { CyclicalPanel } from "./lens2/CyclicalPanel";
import { StructuralPanel } from "./lens1/StructuralPanel";
import { ValuationPanel } from "./lens3/ValuationPanel";

type State = components["schemas"]["GoldStateResponse"];

const sectionStyle: React.CSSProperties = {
  padding: "20px 24px",
  borderBottom: "1px solid var(--border-dim, #1b2030)",
};

type Props = { state: State; replayDate?: string };

export function GoldCompassLayout({ state, replayDate }: Props) {
  return (
    <main style={{ background: "var(--bg-base, #060810)", minHeight: "100vh" }}>
      <GoldCompassHeader obsDate={replayDate ?? state.obs_date} />

      <section role="region" aria-label="KPI strip" style={sectionStyle}>
        <KpiStrip state={state} />
      </section>

      <section
        role="region"
        aria-label="Lens 1 structural flow"
        style={sectionStyle}
      >
        <StructuralPanel structural={state.structural} />
      </section>

      <section
        role="region"
        aria-label="Lens 2 cyclical posture"
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
