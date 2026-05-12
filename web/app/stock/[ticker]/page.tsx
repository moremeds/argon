import { redirect } from "next/navigation";

export default async function StockIndex({
  params,
}: {
  params: Promise<{ ticker: string }>;
}) {
  const { ticker } = await params;
  redirect(`/stock/${ticker}/market-structure`);
}
