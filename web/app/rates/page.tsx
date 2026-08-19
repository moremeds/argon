import { RatesDesk } from "@/components/rates/RatesDesk";
import { api } from "@/lib/api";

export const metadata = { title: "US Rates Factor Desk" };
export const dynamic = "force-dynamic";

async function settle<T>(
  load: () => Promise<T | null>,
  label: string,
): Promise<{ value: T | null; error?: string }> {
  try {
    return { value: await load() };
  } catch (error) {
    const detail = error instanceof Error ? error.message : "unknown API error";
    return { value: null, error: `The ${label} request failed: ${detail}` };
  }
}

export default async function RatesPage() {
  // Settled independently on purpose. The snapshot and the policy comparison come
  // from different jobs; if the policy release ingest is down, the curve is still a
  // fact and the page should say which half is missing rather than blanking both.
  const [snapshot, policy] = await Promise.all([
    settle(() => api.ratesSnapshot(), "rates API"),
    settle(() => api.macroPolicy(), "macro policy API"),
  ]);

  return (
    <RatesDesk
      snapshot={snapshot.value}
      errorMessage={snapshot.error}
      policyComparison={policy.value}
      policyComparisonError={policy.error}
    />
  );
}
