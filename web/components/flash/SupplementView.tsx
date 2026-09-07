import Link from "next/link";

import type { AgentRunIndexRow } from "@/lib/api";

import { Body } from "./Body";
import { CandidateCard } from "./CandidateCard";
import { DecisionBlock } from "./DecisionBlock";
import { EverythingElsePanel } from "./EverythingElsePanel";
import { FocusPanel } from "./FocusPanel";
import { FooterPanel } from "./FooterPanel";
import { GexDeltaTable } from "./GexDeltaTable";
import { GexLevelsTable } from "./GexLevelsTable";
import { Lead } from "./Lead";
import { OneThingPanel } from "./OneThingPanel";
import { Panel } from "./Panel";
import { RiskRegisterPanel } from "./RiskRegisterPanel";
import { RunFaultsPanel } from "./RunFaultsPanel";
import { SectionsPanel } from "./SectionsPanel";
import { StatePill } from "./StatePill";
import { TapeStrip } from "./TapeStrip";
import { ThemesPanel } from "./ThemesPanel";
import {
  faultList,
  viewTickers,
  type BriefView,
  type GexRow,
  type StatusItem,
} from "./view";
import styles from "./flash.module.css";

/**
 * A supplement's whole job is to stay subordinate to the day's premarket
 * report.
 *
 * It opens by SAYING so, with a link back — because a reader who lands on the
 * close transcript first will otherwise read it as the day's call. When no
 * premarket run exists the band says that instead: never a dead link, and
 * never silence, which would read as a report that stands on its own.
 */
export function SupplementView({
  view,
  kind,
  weekKey,
  day,
  runs,
  priorGex,
  priorAsOf,
}: {
  view: BriefView;
  kind: "intraday" | "close";
  weekKey: string;
  day: string;
  runs: AgentRunIndexRow[];
  priorGex?: GexRow[];
  priorAsOf?: string;
}) {
  const hasPremarket = runs.some(
    (r) => String(r.run_day) === day && r.kind === "premarket",
  );
  const lead = view.lead ?? view.headline;
  const tickers = viewTickers(view);
  const label: [string, string] =
    kind === "close" ? ["Close", "read"] : ["Intraday", "read"];
  const statusTitle =
    kind === "close"
      ? "Candidate status · markout at the close"
      : "Candidate status · drift watch";

  return (
    <>
      {view.tape ? (
        <TapeStrip items={view.tape} sourceLine={view.tapeSource} />
      ) : null}
      {lead ? (
        <div style={{ marginTop: 12 }}>
          <Lead label={label} text={lead} size="supplement" />
        </div>
      ) : null}

      <div className={styles.band} style={{ marginTop: 12 }}>
        <span className={`${styles.lbl} ${styles.bandLabel}`}>Supplement</span>
        {hasPremarket ? (
          <p>
            Supplement to the{" "}
            <Link href={`/flash/${weekKey}/${day}?phase=premarket`}>
              premarket report
            </Link>{" "}
            of {day}. The {kind} run is a separate transcript; it settles and
            revises the premarket call rather than replacing it.
          </p>
        ) : (
          <p>
            No premarket run was recorded for this day, so this supplement
            stands alone.
          </p>
        )}
      </div>

      <div className={styles.supgrid}>
        <div className={styles.colL}>
          <OneThingPanel
            oneThing={view.oneThing}
            checks={view.checks}
            changeMyMind={view.changeMyMind}
            tickers={tickers}
          />

          {view.focus && view.focus.rows?.length ? (
            <FocusPanel focus={view.focus} />
          ) : null}

          {view.themes && view.themes.length > 0 ? (
            <ThemesPanel themes={view.themes} />
          ) : null}

          {view.everythingElse && view.everythingElse.length > 0 ? (
            <EverythingElsePanel items={view.everythingElse} />
          ) : null}

          {view.status && view.status.length > 0 ? (
            <Panel
              title={statusTitle}
              tail={view.asOf ? `as of ${view.asOf}` : undefined}
            >
              {view.status.map((item, i) => (
                <StatusBlock
                  key={`${item.title}-${i}`}
                  item={item}
                  last={i === view.status!.length - 1}
                  tickers={tickers}
                />
              ))}
            </Panel>
          ) : null}

          {view.proposal ? (
            <Panel
              title="Proposed at the close"
              tail="survived risk review"
              bodyClassName=""
            >
              <CandidateCard candidate={view.proposal} />
              {view.proposalNote ? (
                <div className={styles.note}>{view.proposalNote}</div>
              ) : null}
            </Panel>
          ) : null}

          {view.decision && view.decision.length > 0 ? (
            <Panel title="The call" tail={kind} bodyClassName="">
              <DecisionBlock rows={view.decision} />
            </Panel>
          ) : null}

          {view.sections && view.sections.length > 0 ? (
            <SectionsPanel
              title="The read"
              tail="full transcript, this run"
              sections={view.sections}
              scroll
              tickers={tickers}
            />
          ) : null}

          {view.recap && view.recap.length > 0 ? (
            <SectionsPanel
              title="Recap"
              tail="recap-writer, verbatim"
              sections={view.recap}
              scroll
              pre
            />
          ) : null}
        </div>

        <div className={styles.colR}>
          {priorGex &&
          priorGex.length > 0 &&
          view.gex &&
          view.gex.length > 0 ? (
            <Panel
              title="Level shifts"
              tail={
                priorAsOf && view.asOf
                  ? `intraday ${priorAsOf} → close ${view.asOf}`
                  : undefined
              }
            >
              <GexDeltaTable before={priorGex} after={view.gex} />
            </Panel>
          ) : view.gex && view.gex.length > 0 ? (
            <Panel
              title="Gamma levels"
              tail={view.asOf ? `gex-reporter · ${view.asOf}` : undefined}
            >
              <GexLevelsTable rows={view.gex} />
            </Panel>
          ) : null}

          {view.riskList && view.riskList.length > 0 ? (
            <RiskRegisterPanel entries={view.riskList} />
          ) : null}

          <RunFaultsPanel
            runId={view.runId}
            faults={[...faultList(view.degradation), ...(view.faults ?? [])]}
          />

          {view.footer ? (
            <FooterPanel footer={view.footer} staleness={view.staleness} />
          ) : null}
        </div>
      </div>
    </>
  );
}

function StatusBlock({
  item,
  last,
  tickers,
}: {
  item: StatusItem;
  last: boolean;
  tickers?: ReadonlySet<string>;
}) {
  return (
    <div
      style={{
        padding: "10px 0",
        borderBottom: last ? undefined : "1px solid rgba(30, 41, 59, .55)",
      }}
    >
      <div
        style={{
          display: "flex",
          gap: 10,
          alignItems: "baseline",
          marginBottom: 4,
        }}
      >
        <span className={styles.mono} style={{ fontSize: 12, fontWeight: 700 }}>
          {item.title}
        </span>
        {item.state ? (
          <span style={{ marginLeft: "auto" }}>
            <StatePill state={item.state} />
          </span>
        ) : null}
      </div>
      <Body text={item.body} tickers={tickers} />
    </div>
  );
}
