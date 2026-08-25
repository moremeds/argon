import { MacroDesk } from "@/components/macro/MacroDesk";
import type { MacroDomainSlot } from "@/components/macro/types";
import { api } from "@/lib/api";

export const metadata = { title: "Macro Context" };
export const dynamic = "force-dynamic";

/** Settled per domain on purpose: four engines, four schedules. One dead publisher must
 *  cost its own card, not the page. */
async function settle(
  domain: "inflation" | "rates" | "usd" | "gold",
): Promise<MacroDomainSlot> {
  try {
    return { value: await api.macroDomainState(domain) };
  } catch (error) {
    const detail = error instanceof Error ? error.message : "unknown API error";
    return { value: null, error: `The ${domain} request failed: ${detail}` };
  }
}

/** The chain verdict is fetched BESIDE the four cards, not instead of them. It answers a
 *  question none of them can: whether the four belong together. A failure to reach it must
 *  not blank the desk, so it settles to null -- which the desk renders as "never
 *  assembled" rather than as a clean chain. */
async function settleSnapshot() {
  try {
    return await api.macroContextSnapshot();
  } catch {
    return null;
  }
}

export default async function MacroPage() {
  const [inflation, rates, usd, gold, snapshot] = await Promise.all([
    settle("inflation"),
    settle("rates"),
    settle("usd"),
    settle("gold"),
    settleSnapshot(),
  ]);

  return (
    <MacroDesk
      domains={{ inflation, policy_rates: rates, usd, gold }}
      snapshot={snapshot}
    />
  );
}
