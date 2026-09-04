import { redirect } from "next/navigation";

import { api } from "@/lib/api";
import { FLASH_TENANT, isoWeekOf, todayEt } from "@/lib/flash/kinds";

export const dynamic = "force-dynamic";

/**
 * `/flash` is a doorway, not a page.
 *
 * There is exactly ONE week view, and it lives at `/flash/<week>`. Rendering a
 * second "current week" here would be two routes showing the same thing with
 * two chances to disagree, so this one only resolves which week is newest and
 * hands over. When nothing is recorded at all it falls through to the current
 * ISO week, whose own page says so honestly rather than 404-ing.
 */
export default async function FlashIndexPage() {
  let weekKey: string | null = null;
  try {
    const weeks = await api.agentRunWeeks(FLASH_TENANT, 1);
    weekKey = weeks.weeks[0]?.week_key ?? null;
  } catch {
    // The week page renders the API-unreachable state; a redirect loop here
    // would hide it.
    weekKey = null;
  }
  redirect(`/flash/${weekKey ?? isoWeekOf(todayEt())}`);
}
