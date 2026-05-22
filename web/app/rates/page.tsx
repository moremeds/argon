import { RatesDesk } from "@/components/rates/RatesDesk";
import { api } from "@/lib/api";

export const metadata = { title: "US Rates Factor Desk" };
export const dynamic = "force-dynamic";

export default async function RatesPage() {
  const snapshot = await api.ratesSnapshot();
  return <RatesDesk snapshot={snapshot} />;
}
