import { redirect } from "next/navigation";

import { api } from "@/lib/api";
import { lastWeekday, pickDoorwayDay } from "@/lib/flash/doorway";
import { DAY_KINDS, FLASH_TENANT, isoWeekOf, todayEt } from "@/lib/flash/kinds";

export const dynamic = "force-dynamic";

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
      ({ day, phase } = pickDoorwayDay(index.runs, today));
    }
  } catch {
    // The week page renders the API-unreachable state; a redirect loop here
    // would hide it.
    redirect(`/flash/${isoWeekOf(today)}`);
  }

  const target = day ?? lastWeekday(today);
  redirect(`/flash/${isoWeekOf(target)}/${target}?phase=${phase}`);
}
