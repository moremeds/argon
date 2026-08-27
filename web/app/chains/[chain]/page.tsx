import { api } from "@/lib/api";
import type { ChainDrilldownResponse } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function ChainDrilldown({
  params,
  searchParams,
}: {
  params: Promise<{ chain: string }>;
  searchParams: Promise<{ layer?: string; engine?: string }>;
}) {
  const { chain } = await params;
  const q = await searchParams;
  let data: ChainDrilldownResponse;
  try {
    data = await api.chainMembers(decodeURIComponent(chain), {
      layer: q.layer,
      engine_version: q.engine,
    });
  } catch (error) {
    const detail = error instanceof Error ? error.message : "unknown API error";
    return (
      <div className="p-6 text-sm text-red-300" role="alert">
        The member request failed: {detail}
      </div>
    );
  }

  return (
    <div className="p-6 text-zinc-200">
      <h1 className="text-xl font-semibold">
        {data.chain}
        {data.layer ? <span className="text-zinc-500"> · {data.layer}</span> : null}
      </h1>
      <p className="mt-1 text-xs text-zinc-500">
        Taxonomy <code>{data.taxonomy_version}</code>. Every row shows how its
        placement was established — a disclosure, an analyst assertion, or a copy
        of the legacy chain rail.
      </p>
      {data.members.length === 0 ? (
        <p className="mt-6 text-sm text-zinc-500">{data.reason}</p>
      ) : (
        <table className="mt-4 w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-zinc-800 text-xs uppercase tracking-wide text-zinc-500">
              <th className="px-2 py-2 text-left">Ticker</th>
              <th className="px-2 py-2 text-left">Layer</th>
              <th className="px-2 py-2 text-left">Placed by</th>
              <th className="px-2 py-2 text-left">Role</th>
              <th className="px-2 py-2 text-right">Magnitude</th>
              <th className="px-2 py-2 text-left">Basis</th>
              <th className="px-2 py-2 text-right">Priority</th>
            </tr>
          </thead>
          <tbody>
            {data.members.map((m) => (
              <tr key={`${m.ticker}-${m.layer}`} className="border-b border-zinc-900">
                <td className="px-2 py-1">
                  <a className="hover:underline" href={`/stock/${m.ticker}`}>
                    {m.ticker}
                  </a>
                </td>
                <td className="px-2 py-1 text-zinc-500">{m.layer}</td>
                <td className="px-2 py-1 text-zinc-500">{m.evidence_class}</td>
                <td className="px-2 py-1 text-zinc-400">{m.role ?? "—"}</td>
                <td className="px-2 py-1 text-right tabular-nums">
                  {/* A missing magnitude is the NORMAL state and says so, rather
                      than rendering an em dash that reads like a data gap. */}
                  {m.magnitude == null ? (
                    <span className="text-zinc-600">not disclosed</span>
                  ) : (
                    `${(m.magnitude * 100).toFixed(1)}%`
                  )}
                </td>
                <td className="px-2 py-1 text-xs text-zinc-500">
                  {m.magnitude_basis ?? "—"}
                  {m.source_ref ? (
                    <span className="ml-1 text-zinc-600">({m.source_ref})</span>
                  ) : null}
                </td>
                <td className="px-2 py-1 text-right tabular-nums text-zinc-400">
                  {m.priority == null ? "na" : m.priority.toFixed(2)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
