import { api } from "@/lib/api";
import type {
  AgentRunIndexRow,
  AgentRunResponse,
  AgentRunWeekListResponse,
  AgentRunWeekResponse,
} from "@/lib/api";
import { FLASH_TENANT } from "@/lib/flash/kinds";

import { FlashWeekPage } from "@/components/flash/FlashWeekPage";

export const dynamic = "force-dynamic";

/**
 * The newest recorded row of one kind in this week's index.
 *
 * THE WEEK'S RUNS ARE NOT FILED UNDER FRIDAY. helium sends `week_key`
 * explicitly and files each run under its own `run_day` — a Frank 复盘 for
 * W36 carries run_day 2026-09-07, the Monday AFTER the week it reviews. Asking
 * the API for `(frank, friday)` finds nothing and renders "no review attached"
 * over a review that exists. The index is the only authority on which day a
 * week-scoped run actually landed on.
 */
function newestOfKind(
  runs: AgentRunIndexRow[],
  kind: string,
): AgentRunIndexRow | undefined {
  return runs
    .filter((r) => r.kind === kind)
    .sort((a, b) =>
      String(a.run_day) === String(b.run_day)
        ? b.version_no - a.version_no
        : String(a.run_day) < String(b.run_day)
          ? 1
          : -1,
    )[0];
}

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
