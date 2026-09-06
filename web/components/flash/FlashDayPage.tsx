import type { AgentRunIndexRow, AgentRunResponse, AgentRunWeek } from "@/lib/api";
import { KIND_LABEL, todayEt, type DayKind } from "@/lib/flash/kinds";

import { FlashTopbar } from "./FlashTopbar";
import { NoRunRecorded, PlaceholderBand } from "./EmptyStates";
import { PhaseTabs } from "./PhaseTabs";
import { PremarketView } from "./PremarketView";
import { SupplementView } from "./SupplementView";
import { WeekStrip } from "./WeekStrip";
import { SUPPORTED_SCHEMA_VERSIONS, asBriefView } from "./view";
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
  prior,
}: {
  weekKey: string;
  day: string;
  kind: DayKind;
  runs: AgentRunIndexRow[];
  weeks: AgentRunWeek[];
  run: AgentRunResponse | null;
  /** The intraday run, when this is the close view — for the gamma delta. */
  prior?: AgentRunResponse | null;
}) {
  const view = run ? asBriefView(run) : null;
  const priorView = prior ? asBriefView(prior) : null;

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
          {`The ${KIND_LABEL[kind] ?? kind} run for ${day} arrived as schema version ${run.schema_version}; this build of argon renders version(s) ${SUPPORTED_SCHEMA_VERSIONS.join(", ")}. The run is stored and nothing is lost — the fix is an argon deploy, not a re-run.`}
        </PlaceholderBand>
      ) : kind === "premarket" ? (
        <PremarketView view={view} />
      ) : (
        <SupplementView
          view={view}
          kind={kind}
          weekKey={weekKey}
          day={day}
          runs={runs}
          priorGex={priorView?.gex}
          priorAsOf={priorView?.asOf}
        />
      )}
    </main>
  );
}

