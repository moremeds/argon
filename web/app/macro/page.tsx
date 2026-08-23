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

export default async function MacroPage() {
  const [inflation, rates, usd, gold] = await Promise.all([
    settle("inflation"),
    settle("rates"),
    settle("usd"),
    settle("gold"),
  ]);

  return (
    <MacroDesk
      domains={{ inflation, policy_rates: rates, usd, gold }}
    />
  );
}
