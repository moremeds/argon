import type { AgentRunIndexRow, AgentRunResponse, AgentRunWeek } from "@/lib/api";
import { todayEt } from "@/lib/flash/kinds";
import { viewDigest } from "@/lib/flash/view-digest";

import { FlashTopbar } from "./FlashTopbar";
import { WeekStrip } from "./WeekStrip";
import { WeeklyView } from "./WeeklyView";
import styles from "./flash.module.css";

/** The week view. `selectedDay` is undefined, so the weekly card is selected. */
export function FlashWeekPage({
  weekKey,
  runs,
  weeks,
  weekly,
  frank,
}: {
  weekKey: string;
  runs: AgentRunIndexRow[];
  weeks: AgentRunWeek[];
  weekly: AgentRunResponse | null;
  frank: AgentRunResponse | null;
}) {
  return (
    <main className={styles.flash}>
      <FlashTopbar today={todayEt()} />
      <WeekStrip weekKey={weekKey} runs={runs} weeks={weeks} />
      <div data-testid="flash-report" data-run-id={weekly?.run_id} data-view-sha256={weekly ? viewDigest(weekly.view) : undefined} style={{ marginTop: 18 }}>
        <WeeklyView
          weekKey={weekKey}
          runs={runs}
          weekly={weekly}
          frank={frank}
        />
      </div>
    </main>
  );
}
