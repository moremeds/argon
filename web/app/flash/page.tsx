import { redirect } from "next/navigation";

import { api } from "@/lib/api";
import {
  DAY_KINDS,
  FLASH_TENANT,
  isDayKind,
  isoWeekOf,
  todayEt,
} from "@/lib/flash/kinds";

export const dynamic = "force-dynamic";

/**
 * The most recent Mon–Fri on or before `day`.
 *
 * There is NO holiday calendar here, deliberately: argon does not know which
 * sessions the exchange closed, and inventing one would move the doorway to a
 * day that never traded. This only skips the weekend, which is the one thing
 * about the calendar that is certain. It is a fallback for a week with no
 * recorded daily run at all — the day page then says so itself.
 */
function lastWeekday(day: string): string {
  const [y, m, d] = day.split("-").map(Number);
  const date = new Date(Date.UTC(y, (m ?? 1) - 1, d ?? 1));
  while (date.getUTCDay() === 0 || date.getUTCDay() === 6) {
    date.setUTCDate(date.getUTCDate() - 1);
  }
  return date.toISOString().slice(0, 10);
}

/**
 * `/flash` is a doorway, not a page.
 *
 * It lands on a DAY, not a week: the operator opens Flash to read today's
 * brief, and a week strip is one more click between them and it. The target is
 * the newest recorded day that is not in the future — if this morning's
 * premarket ran, that is today — and the phase is the latest kind recorded on
 * that day, so the doorway opens on the freshest thing the day has rather than
 * on premarket after the close has been written.
 *
 * Nothing is rendered here. There is exactly ONE day view and ONE week view,
 * and a third route repeating either would be two pages with two chances to
 * disagree. When the API cannot be reached at all it falls through to the
 * current ISO week, whose own page renders the unreachable state honestly
 * rather than 404-ing or looping.
 */
export default async function FlashIndexPage() {
  const today = todayEt();

  let weekKey: string | null = null;
  let day: string | null = null;
  let phase: string = DAY_KINDS[0];
  try {
    const weeks = await api.agentRunWeeks(FLASH_TENANT, 1);
    weekKey = weeks.weeks[0]?.week_key ?? null;

    if (weekKey) {
      const index = await api.agentRunWeek(FLASH_TENANT, weekKey);
      const daily = index.runs.filter(
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
    }
  } catch {
    // The week page renders the API-unreachable state; a redirect loop here
    // would hide it.
    redirect(`/flash/${isoWeekOf(today)}`);
  }

  const target = day ?? lastWeekday(today);
  redirect(`/flash/${isoWeekOf(target)}/${target}?phase=${phase}`);
}
