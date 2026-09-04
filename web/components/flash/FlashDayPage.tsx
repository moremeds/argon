import type { AgentRunIndexRow, AgentRunResponse, AgentRunWeek } from "@/lib/api";
import { KIND_LABEL, todayEt, type DayKind } from "@/lib/flash/kinds";

import { FlashTopbar } from "./FlashTopbar";
import { NoRunRecorded, PlaceholderBand } from "./EmptyStates";
import { PhaseTabs } from "./PhaseTabs";
import { Lead } from "./Lead";
import { PremarketView } from "./PremarketView";
import { SectionsPanel } from "./SectionsPanel";
import { TapeStrip } from "./TapeStrip";
import { WeekStrip } from "./WeekStrip";
import { SUPPORTED_SCHEMA_VERSION, asBriefView } from "./view";
import styles from "./flash.module.css";

/**
 * One day, one phase. Four outcomes, all of them said out loud:
 *
 *   no run          → the empty state, naming the audit it ran
 *   unreadable      → the version that arrived vs the version this build draws
 *   premarket       → the report
 *   supplement      → the supplement view
 *
 * The fourth branch never silently becomes the third: a supplement rendered as
 * a report would claim the day's call was made at 17:00Z.
 */
export function FlashDayPage({
  weekKey,
  day,
  kind,
  runs,
  weeks,
  run,
}: {
  weekKey: string;
  day: string;
  kind: DayKind;
  runs: AgentRunIndexRow[];
  weeks: AgentRunWeek[];
  run: AgentRunResponse | null;
}) {
  const view = run ? asBriefView(run) : null;

  return (
    <main className={styles.flash}>
      <FlashTopbar today={todayEt()} />
      <WeekStrip
        weekKey={weekKey}
        runs={runs}
        weeks={weeks}
        selectedDay={day}
      />
      <PhaseTabs
        weekKey={weekKey}
        day={day}
        runs={runs}
        selected={kind}
        asOf={view?.asOf ?? run?.created_at}
      />

      {!run ? (
        <NoRunRecorded day={day} kind={kind} isFuture={day > todayEt()} />
      ) : !view ? (
        <PlaceholderBand label="Unrenderable version">
          {`The ${KIND_LABEL[kind] ?? kind} run for ${day} arrived as schema version ${run.schema_version}; this build of argon renders version ${SUPPORTED_SCHEMA_VERSION}. The run is stored and nothing is lost — the fix is an argon deploy, not a re-run.`}
        </PlaceholderBand>
      ) : kind === "premarket" ? (
        <PremarketView view={view} />
      ) : (
        <SupplementBody view={view} kind={kind} />
      )}
    </main>
  );
}

/**
 * A supplement's shared opening: its own tape, its own read.
 *
 * It never wears the premarket labels. "Today in one sentence" over a 17:00Z
 * transcript would claim the day's call was made at 17:00Z, and the whole
 * point of a supplement is that it settles the morning's call rather than
 * replacing it.
 */
function SupplementBody({
  view,
  kind,
}: {
  view: NonNullable<ReturnType<typeof asBriefView>>;
  kind: DayKind;
}) {
  const lead = view.lead ?? view.headline;
  const label: [string, string] =
    kind === "close" ? ["Close", "read"] : ["Intraday", "read"];
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
      {view.sections && view.sections.length > 0 ? (
        <div style={{ marginTop: 12 }}>
          <SectionsPanel
            title="Run sections"
            tail="full transcript, this run"
            sections={view.sections}
            scroll
          />
        </div>
      ) : null}
    </>
  );
}
