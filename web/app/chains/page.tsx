import { ChainMatrix } from "@/components/chains/ChainMatrix";
import { api } from "@/lib/api";
import type { ChainMatrixResponse } from "@/lib/api";

export const metadata = { title: "Chain Matrix" };
export const dynamic = "force-dynamic";

export default async function ChainsPage({
  searchParams,
}: {
  searchParams: Promise<{ engine?: string; domain?: string }>;
}) {
  const params = await searchParams;
  let data: ChainMatrixResponse;
  try {
    data = await api.chainMatrix({
      engine_version: params.engine,
      domain: params.domain,
    });
  } catch (error) {
    const detail = error instanceof Error ? error.message : "unknown API error";
    return (
      <div className="p-6 text-sm text-red-300" role="alert">
        The chain matrix request failed: {detail}
      </div>
    );
  }
  return <ChainMatrix data={data} engine={params.engine} />;
}
