import Link from "next/link";

import type { AgentRunIndexRow, AgentRunWeek } from "@/lib/api";
import { DAY_KINDS, PIP_LABEL, weekDays, weekRange } from "@/lib/flash/kinds";

import styles from "./flash.module.css";

/**
 * Five day cards plus the weekly card.
 *
 * Anchors, not buttons: navigation IS a URL change, and a click handler here
 * would only re-implement the browser — losing the middle-click, the back
 * button and the copyable link in the process.
 *
 * Prev/next walk the RECORDED weeks, never the calendar. A calendar arrow
 * lands on an empty week and reads as data loss; a disabled arrow says the
 * truth, which is that nothing earlier was ever written.
 */
export function WeekStrip({
  weekKey,
  runs,
  weeks,
  selectedDay,
}: {
  weekKey: string;
  runs: AgentRunIndexRow[];
  weeks: AgentRunWeek[];
  selectedDay?: string;
}) {
  const days = weekDays(weekKey);
  const { first, last } = weekRange(weekKey);

  const byDay = new Map<string, Set<string>>();
  for (const run of runs) {
    const day = String(run.run_day);
    if (!byDay.has(day)) byDay.set(day, new Set());
    byDay.get(day)!.add(run.kind);
  }
  const headlineOf = (day: string, kind: string) =>
    runs.find(
      (r) => String(r.run_day) === day && r.kind === kind && r.headline,
    )?.headline ?? "";

  const recordedDays = days.filter(({ date }) => byDay.has(date)).length;
  const weeklyHeadline = headlineOf(last, "weekly");

  // The list arrives newest-first, so the EARLIER week is index + 1.
  const here = weeks.findIndex((w) => w.week_key === weekKey);
  const earlier = here >= 0 ? weeks[here + 1] : weeks[0];
  const later = here > 0 ? weeks[here - 1] : undefined;
  const weekNo = weekKey.split("-")[1] ?? weekKey;

  return (
    <>
      <div className={styles.weekhead}>
        <span className={styles.lbl}>Week</span>
        <WeekNav
          testid="flash-week-prev"
          week={earlier}
          glyph="‹"
          absent="No earlier week has a recorded run."
        />
        <span className={styles.wkrange}>
          {first} → {last}
        </span>
        <WeekNav
          testid="flash-week-next"
          week={later}
          glyph="›"
          absent="No later week has a recorded run."
        />
        <span className={styles.wkcount}>
          {weekNo} · {recordedDays} of 5 days has a recorded run
        </span>
      </div>

      <div className={styles.strip}>
        {days.map(({ date, dow }) => {
          const kinds = byDay.get(date);
          const headline = headlineOf(date, "premarket");
          return (
            <Link
              key={date}
              href={`/flash/${weekKey}/${date}`}
              className={styles.dcard}
              data-testid={`flash-day-${date}`}
              aria-pressed={date === selectedDay}
            >
              <span className={styles.dh}>
                <span className={styles.dow}>{dow}</span>
                <span className={styles.dt}>{date.slice(5)}</span>
              </span>
              {kinds && headline ? (
                <span className={styles.one}>{headline}</span>
              ) : (
                <span className={`${styles.one} ${styles.norun}`}>
                  {kinds ? "no premarket run" : "no run recorded"}
                </span>
              )}
              <span className={styles.pips}>
                {DAY_KINDS.map((kind) => (
                  <span
                    key={kind}
                    className={styles.pip}
                    data-testid={`pip-${kind}`}
                    data-on={String(kinds?.has(kind) ?? false)}
                    title={kind}
                  >
                    {PIP_LABEL[kind]}
                  </span>
                ))}
              </span>
            </Link>
          );
        })}

        <Link
          href={`/flash/${weekKey}`}
          className={`${styles.dcard} ${styles.wkcard}`}
          data-testid="flash-day-weekly"
          aria-pressed={selectedDay == null}
        >
          <span className={styles.dh}>
            <span className={styles.dow}>WEEK</span>
            <span className={styles.dt}>{weekNo}</span>
          </span>
          {weeklyHeadline ? (
            <span className={styles.one}>{weeklyHeadline}</span>
          ) : (
            <span className={`${styles.one} ${styles.norun}`}>
              not generated yet
            </span>
          )}
          <span className={styles.pips}>
            <span
              className={styles.pip}
              data-testid="pip-weekly"
              data-on={String(byDay.get(last)?.has("weekly") ?? false)}
              title="weekly"
            >
              S
            </span>
          </span>
        </Link>
      </div>
    </>
  );
}

function WeekNav({
  testid,
  week,
  glyph,
  absent,
}: {
  testid: string;
  week?: AgentRunWeek;
  glyph: string;
  absent: string;
}) {
  if (!week) {
    return (
      <button
        type="button"
        className={styles.wknav}
        data-testid={testid}
        disabled
        title={absent}
      >
        {glyph}
      </button>
    );
  }
  return (
    <Link
      href={`/flash/${week.week_key}`}
      className={styles.wknav}
      data-testid={testid}
      title={`Week ${week.week_key}`}
    >
      {glyph}
    </Link>
  );
}
