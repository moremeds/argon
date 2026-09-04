import { CandidateCard } from "./CandidateCard";
import { CoveragePanel } from "./CoveragePanel";
import { DecisionBlock } from "./DecisionBlock";
import { PlaceholderBand } from "./EmptyStates";
import { GammaProfilePanel } from "./GammaProfilePanel";
import { Lead } from "./Lead";
import { OvernightPanel } from "./OvernightPanel";
import { Panel } from "./Panel";
import { PolicyPathPanel } from "./PolicyPathPanel";
import { RiskRegisterPanel } from "./RiskRegisterPanel";
import { SchedulePanel } from "./SchedulePanel";
import { SectionsPanel } from "./SectionsPanel";
import { TapeStrip } from "./TapeStrip";
import type { BriefView } from "./view";
import styles from "./flash.module.css";

const FOOTER =
  "All structures are defined-risk. No quantities, position sizes or account information appear anywhere in this flash.";

/**
 * The day's report. Everything else that day is a supplement to this.
 *
 * A run that recorded nothing says so in one line and stops — it does NOT fall
 * through to an empty decision block, because an empty grid of the reviewer's
 * keys reads as a reviewer who answered nothing rather than a run that never
 * reached the reviewer.
 */
export function PremarketView({ view }: { view: BriefView }) {
  if (view.empty) {
    return (
      <p className={styles.provenance} style={{ display: "block", padding: 12 }}>
        This run completed but recorded no content for {view.date}.
      </p>
    );
  }

  const lead = view.lead ?? view.headline;

  return (
    <>
      {view.tape ? (
        <TapeStrip items={view.tape} sourceLine={view.tapeSource} />
      ) : null}
      {lead ? (
        <div style={{ marginTop: 12 }}>
          <Lead label={["Today in", "one sentence"]} text={lead} />
        </div>
      ) : null}
      {view.degradation && view.degradation.length > 0 ? (
        <div style={{ marginTop: 12 }}>
          <PlaceholderBand label="Run degraded">
            {view.degradation.join(" · ")}
          </PlaceholderBand>
        </div>
      ) : null}

      <div className={styles.cols}>
        <div className={styles.colL}>
          {view.decision && view.decision.length > 0 ? (
            <Panel title="Bottom line · decision block" bodyClassName="">
              <DecisionBlock rows={view.decision} />
            </Panel>
          ) : null}

          {view.candidates && view.candidates.length > 0 ? (
            <div>
              <div className={styles.lbl} style={{ padding: "2px 0 8px" }}>
                Candidates · per contract, no size
              </div>
              <div className={styles.stack}>
                {view.candidates.map((c) => (
                  <CandidateCard key={c.id} candidate={c} />
                ))}
              </div>
            </div>
          ) : null}

          {view.sections && view.sections.length > 0 ? (
            <SectionsPanel title="Sections" sections={view.sections} />
          ) : null}
        </div>

        <div className={styles.colR}>
          <OvernightPanel items={view.overnight ?? []} />
          {view.schedule && view.schedule.length > 0 ? (
            <SchedulePanel items={view.schedule} />
          ) : null}
          {view.policy ? <PolicyPathPanel path={view.policy} /> : null}
          {view.gamma && view.gamma.length > 0 ? (
            <GammaProfilePanel profiles={view.gamma} />
          ) : null}
          {view.riskList && view.riskList.length > 0 ? (
            <RiskRegisterPanel entries={view.riskList} tail="dropped this run" />
          ) : null}
          {view.coverage ? <CoveragePanel coverage={view.coverage} /> : null}
        </div>
      </div>

      <p
        style={{
          margin: "14px 0 0",
          fontSize: 11.5,
          color: "var(--text-muted)",
        }}
      >
        {FOOTER}
      </p>
    </>
  );
}
