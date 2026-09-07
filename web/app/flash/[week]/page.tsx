import { api } from "@/lib/api";
import type {
  AgentRunResponse,
  AgentRunWeekListResponse,
  AgentRunWeekResponse,
} from "@/lib/api";
import { FLASH_TENANT, newestOfKind } from "@/lib/flash/kinds";

import { FlashWeekPage } from "@/components/flash/FlashWeekPage";

export const dynamic = "force-dynamic";

/**
 * The week view: five days, the weekly summary, and the Frank supplement.
 *
 * Two round trips on purpose — the index says WHICH days the week-scoped runs
 * landed on, and only then can each be fetched by its own `(kind, run_day)`.
 */
export default async function FlashWeekRoute({
  params,
}: {
  params: Promise<{ week: string }>;
}) {
  const { week } = await params;
  const weekKey = decodeURIComponent(week);

  let index: AgentRunWeekResponse;
  let weeks: AgentRunWeekListResponse;
  let weekly: AgentRunResponse | null = null;
  let frank: AgentRunResponse | null = null;
  try {
    [index, weeks] = await Promise.all([
      api.agentRunWeek(FLASH_TENANT, weekKey),
      api.agentRunWeeks(FLASH_TENANT),
    ]);
    const weeklyRow = newestOfKind(index.runs, "weekly");
    const frankRow = newestOfKind(index.runs, "frank");
    [weekly, frank] = await Promise.all([
      weeklyRow
        ? api.agentRun(FLASH_TENANT, "weekly", String(weeklyRow.run_day))
        : Promise.resolve(null),
      frankRow
        ? api.agentRun(FLASH_TENANT, "frank", String(frankRow.run_day))
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
    <FlashWeekPage
      weekKey={weekKey}
      runs={index.runs}
      weeks={weeks.weeks}
      weekly={weekly}
      frank={frank}
    />
  );
}
