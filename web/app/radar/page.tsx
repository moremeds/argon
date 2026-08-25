import { RadarTable } from "@/components/radar/RadarTable";
import { api } from "@/lib/api";
import type { RadarResponse } from "@/lib/api";

export const metadata = { title: "Research Radar" };
export const dynamic = "force-dynamic";

export default async function RadarPage({
  searchParams,
}: {
  searchParams: Promise<{ engine?: string; tier?: string }>;
}) {
  const params = await searchParams;
  let data: RadarResponse;
  try {
    data = await api.radar({
      tier: params.tier ?? "ranked",
      engine_version: params.engine,
      limit: 300,
    });
  } catch (error) {
    // A transport failure is NOT one of the six data states — rendering it as
    // `no_coverage` would blame the companies for a broken request.
    const detail = error instanceof Error ? error.message : "unknown API error";
    return (
      <div className="p-6 text-sm text-red-300" role="alert">
        The Radar request failed: {detail}
      </div>
    );
  }
  return <RadarTable data={data} />;
}
