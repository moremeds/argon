import type { AgentRunIndexRow } from "@/lib/api";
import { DAY_KINDS, isDayKind } from "@/lib/flash/kinds";

/**
 * The most recent Mon–Fri on or before `day`.
 *
 * There is NO holiday calendar here, deliberately: argon does not know which
 * sessions the exchange closed, and inventing one would move the doorway to a
 * day that never traded. This only skips the weekend, which is the one thing
 * about the calendar that is certain. It is a fallback for a week with no
 * recorded daily run at all — the day page then says so itself.
 */
export function lastWeekday(day: string): string {
  const [y, m, d] = day.split("-").map(Number);
  const date = new Date(Date.UTC(y, (m ?? 1) - 1, d ?? 1));
  while (date.getUTCDay() === 0 || date.getUTCDay() === 6) {
    date.setUTCDate(date.getUTCDate() - 1);
  }
  return date.toISOString().slice(0, 10);
}

/**
 * The doorway's target inside one week's run index: the newest recorded day
 * that is not after `today`, and the latest phase recorded on that day.
 * `day` is null when the week has no daily run on or before `today`; `phase`
 * then stays the first day kind.
 */
export function pickDoorwayDay(
  runs: AgentRunIndexRow[],
  today: string,
): { day: string | null; phase: string } {
  let day: string | null = null;
  let phase: string = DAY_KINDS[0];
  const daily = runs.filter(
    (r) => isDayKind(r.kind) && String(r.run_day) <= today,
  );
  for (const run of daily) {
    const runDay = String(run.run_day);
    if (day === null || runDay > day) day = runDay;
  }
  if (day !== null) {
    // The latest phase recorded that day, in the day's own order. A close
    // run is the day's last word; opening on premarket after it exists
    // would show the reader the oldest view of a finished day.
    const onDay = daily.filter((r) => String(r.run_day) === day);
    for (const kind of DAY_KINDS) {
      if (onDay.some((r) => r.kind === kind)) phase = kind;
    }
  }
  return { day, phase };
}
