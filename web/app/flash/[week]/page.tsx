import { api } from "@/lib/api";
import type { AgentRunResponse, AgentRunWeekResponse } from "@/lib/api";
import type { AgentRunWeekListResponse } from "@/lib/api";
import { FLASH_TENANT, weekRange } from "@/lib/flash/kinds";

export const dynamic = "force-dynamic";

/**
 * The week view: five days, the weekly summary, and the Frank supplement.
 *
 * Everything the page needs is fetched in one `Promise.all` — the index, the
 * recorded-week list (prev/next walk RECORDED weeks, never the calendar) and
 * the two week-scoped runs, which helium files under the week's Friday.
 */
export default async function FlashWeekPage({
  params,
}: {
  params: Promise<{ week: string }>;
}) {
  const { week } = await params;
  const weekKey = decodeURIComponent(week);
  const { last } = weekRange(weekKey);

  let index: AgentRunWeekResponse;
  let weeks: AgentRunWeekListResponse;
  let weekly: AgentRunResponse | null;
  let frank: AgentRunResponse | null;
  try {
    [index, weeks, weekly, frank] = await Promise.all([
      api.agentRunWeek(FLASH_TENANT, weekKey),
      api.agentRunWeeks(FLASH_TENANT),
      api.agentRun(FLASH_TENANT, "weekly", last),
      api.agentRun(FLASH_TENANT, "frank", last),
    ]);
  } catch (error) {
    const detail = error instanceof Error ? error.message : "unknown API error";
    return (
      <main role="alert" style={{ padding: 24 }}>
        Flash could not reach the agent-run API: {detail}
      </main>
    );
  }

  return (
    <main data-testid="flash-week" data-week={weekKey}>
      <p hidden>
        {index.runs.length} runs · {weeks.weeks.length} recorded weeks ·
        {weekly ? " weekly" : ""}
        {frank ? " frank" : ""}
      </p>
    </main>
  );
}
