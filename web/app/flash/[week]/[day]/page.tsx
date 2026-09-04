import { api } from "@/lib/api";
import type { AgentRunResponse, AgentRunWeekResponse } from "@/lib/api";
import type { AgentRunWeekListResponse } from "@/lib/api";
import { DAY_KINDS, FLASH_TENANT, isDayKind } from "@/lib/flash/kinds";

import { FlashDayPage as FlashDayView } from "@/components/flash/FlashDayPage";

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
  let prior: AgentRunResponse | null;
  try {
    [index, weeks, run, prior] = await Promise.all([
      api.agentRunWeek(FLASH_TENANT, weekKey),
      api.agentRunWeeks(FLASH_TENANT),
      api.agentRun(FLASH_TENANT, kind, runDay),
      // The close view's delta table needs the intraday run itself, not its
      // index row: index rows deliberately carry no document.
      kind === "close"
        ? api.agentRun(FLASH_TENANT, "intraday", runDay)
        : Promise.resolve(null),
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
    <FlashDayView
      weekKey={weekKey}
      day={runDay}
      kind={kind}
      runs={index.runs}
      weeks={weeks.weeks}
      run={run}
      prior={prior}
    />
  );
}
