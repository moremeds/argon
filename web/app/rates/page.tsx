import { RatesDesk } from "@/components/rates/RatesDesk";
import { api } from "@/lib/api";

export const metadata = { title: "US Rates Factor Desk" };
export const dynamic = "force-dynamic";

export default async function RatesPage() {
  let snapshot: Awaited<ReturnType<typeof api.ratesSnapshot>> = null;
  let errorMessage: string | undefined;
  try {
    snapshot = await api.ratesSnapshot();
  } catch (error) {
    const detail = error instanceof Error ? error.message : "unknown API error";
    errorMessage = `The rates API request failed: ${detail}`;
  }
  return <RatesDesk snapshot={snapshot} errorMessage={errorMessage} />;
}
