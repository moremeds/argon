import type { AgentRunIndexRow, AgentRunResponse } from "@/lib/api";
import { weekDays, weekRange } from "@/lib/flash/kinds";

import { Panel } from "./Panel";
import { SectionsPanel } from "./SectionsPanel";
import { asBriefView } from "./view";
import styles from "./flash.module.css";

/**
 * The week: five one-liners, then the outlook and the Frank supplement.
 *
 * Frank 复盘 attaches HERE, to the weekly summary — not to a day. It is an
 * external weekly review of the week just ended, and filing it under Monday
 * would date it to a session it does not describe.
 */
export function WeeklyView({
  weekKey,
  runs,
  weekly,
  frank,
}: {
  weekKey: string;
  runs: AgentRunIndexRow[];
  weekly: AgentRunResponse | null;
  frank: AgentRunResponse | null;
}) {
  const days = weekDays(weekKey);
  const { first, last } = weekRange(weekKey);
  const weeklyView = weekly ? asBriefView(weekly) : null;
  const frankView = frank ? asBriefView(frank) : null;

  return (
    <>
      <Panel
        title="The week, one line a day"
        tail={`${first} → ${last}`}
        bodyClassName=""
      >
        {days.map(({ date, dow }) => {
          const forDay = runs.filter((r) => String(r.run_day) === date);
          const oneLiner =
            forDay.find((r) => r.kind === "premarket" && r.headline)
              ?.headline ?? "";
          return (
            <div
              key={date}
              className={styles.wkrow}
              data-testid={`weekly-row-${date}`}
            >
              <div className={styles.wkrowDay}>
                <span className={styles.dow}>{dow}</span>
                <span className={styles.dt}>{date}</span>
              </div>
              <div className={styles.wkrowText}>
                {oneLiner ? (
                  <span
                    style={{
                      fontSize: 12.5,
                      lineHeight: 1.55,
                      color: "var(--text-secondary)",
                      maxWidth: "110ch",
                    }}
                  >
                    {oneLiner}
                  </span>
                ) : (
                  <span className={styles.norun}>no run recorded</span>
                )}
                <span
                  className={`${styles.mono} ${styles.wkrowRuns}`}
                  style={{
                    color:
                      forDay.length > 0
                        ? "var(--positive)"
                        : "var(--text-muted)",
                  }}
                >
                  {forDay.length} {forDay.length === 1 ? "run" : "runs"}
                </span>
              </div>
            </div>
          );
        })}
      </Panel>

      <div className={styles.cols}>
        <div className={styles.colL}>
          {weeklyView &&
          weeklyView.sections &&
          weeklyView.sections.length > 0 ? (
            <SectionsPanel
              title="Week ahead"
              tail={weeklyView.asOf}
              sections={weeklyView.sections}
            />
          ) : (
            <Panel title="Week ahead" tail="not yet available">
              <SlotEmpty
                headline="Generated Sunday morning"
                body="The outlook block is written by the weekly job, which runs Sunday 08:00 ET. Until it has run for this week there is nothing to show."
                ghost={88}
              />
            </Panel>
          )}
        </div>
        <div className={styles.colR}>
          {frankView && frankView.sections && frankView.sections.length > 0 ? (
            <SectionsPanel
              title="Frank 复盘"
              tail="supplement slot"
              sections={frankView.sections}
              pre
            />
          ) : (
            <Panel title="Frank 复盘" tail="supplement slot">
              <SlotEmpty
                headline="No review attached"
                body="An external weekly review, attached to the weekly summary rather than to any single day. None recorded for this week."
                ghost={70}
              />
            </Panel>
          )}
        </div>
      </div>
    </>
  );
}

function SlotEmpty({
  headline,
  body,
  ghost,
}: {
  headline: string;
  body: string;
  ghost: number;
}) {
  return (
    <>
      <div
        className={styles.empty}
        style={{ border: "none", background: "none", padding: "24px 12px" }}
      >
        <span className={styles.big}>{headline}</span>
        <p>{body}</p>
      </div>
      <div className={styles.skel} aria-hidden="true">
        <div className={styles.ghostbox} style={{ height: ghost }} />
      </div>
    </>
  );
}
