import { api } from "@/lib/api";
import type { AgentRunResponse, AgentRunWeekResponse } from "@/lib/api";
import type { AgentRunWeekListResponse } from "@/lib/api";
import { DAY_KINDS, FLASH_TENANT, isDayKind } from "@/lib/flash/kinds";

export const dynamic = "force-dynamic";

/**
 * One day, one phase.
 *
 * The phase is a SEARCH PARAM, not a path segment. The week strip and the tab
 * strip both live on this page and read the same week index; a segment would
 * turn every tab click into a different route with its own loading state for
 * data it already has.
 */
export default async function FlashDayPage({
  params,
  searchParams,
}: {
  params: Promise<{ week: string; day: string }>;
  searchParams: Promise<{ phase?: string }>;
}) {
  const { week, day } = await params;
  const { phase } = await searchParams;
  const weekKey = decodeURIComponent(week);
  const runDay = decodeURIComponent(day);
  const kind = phase && isDayKind(phase) ? phase : DAY_KINDS[0];

  let index: AgentRunWeekResponse;
  let weeks: AgentRunWeekListResponse;
  let run: AgentRunResponse | null;
  try {
    [index, weeks, run] = await Promise.all([
      api.agentRunWeek(FLASH_TENANT, weekKey),
      api.agentRunWeeks(FLASH_TENANT),
      api.agentRun(FLASH_TENANT, kind, runDay),
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
    <main data-testid="flash-day" data-week={weekKey} data-phase={kind}>
      <p hidden>
        {index.runs.length} runs · {weeks.weeks.length} recorded weeks ·
        {run ? ` ${run.run_id}` : " no run"}
      </p>
    </main>
  );
}
