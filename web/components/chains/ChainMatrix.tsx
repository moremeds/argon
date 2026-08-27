"use client";

import { useMemo, useState } from "react";
import type { ChainCell, ChainMatrixResponse } from "@/lib/api";

/** A chain × layer matrix that describes and does not conduct.
 *
 *  Two rules drive every visual choice here:
 *
 *  1. **Nothing propagates.** `layer_rank` orders layers upstream → downstream
 *     as a READING order. Argon measured the alternative: the capex-demand
 *     ledger's cross-name relationship collapsed from +0.247 to +0.015 (p=0.44)
 *     once same-sector pairs were compared, so a chain edge carries no
 *     demonstrated forward information. No arrows, no flow, no node-link view.
 *  2. **An unavailable cell is hatched, never blank.** A blank cell reads as
 *     "nothing here"; these cells abstain for a stated reason, and the reason is
 *     the useful part.
 */

function cellKey(c: ChainCell) {
  return `${c.chain}::${c.layer}`;
}

function Cell({
  cell,
  onSelect,
}: {
  cell: ChainCell;
  onSelect: (c: ChainCell) => void;
}) {
  const abstains = cell.abstain_reason != null;
  return (
    <button
      type="button"
      onClick={() => onSelect(cell)}
      title={
        abstains
          ? cell.abstain_reason ?? ""
          : `${cell.with_result} of ${cell.members} members carry a compatible result`
      }
      className={`w-full rounded border px-2 py-1.5 text-left transition ${
        abstains
          ? // Hatched, not invisible. The reason is why the cell exists.
            "border-zinc-800 bg-[repeating-linear-gradient(45deg,transparent,transparent_4px,rgba(120,120,130,.13)_4px,rgba(120,120,130,.13)_8px)] text-zinc-500"
          : "border-zinc-700 bg-zinc-900/60 text-zinc-200 hover:border-zinc-500"
      }`}
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="truncate text-xs">{cell.layer}</span>
        <span className="tabular-nums text-xs text-zinc-500">
          {cell.with_result}/{cell.members}
        </span>
      </div>
      <div className="mt-0.5 tabular-nums text-sm">
        {abstains ? (
          <span className="text-zinc-600">abstains</span>
        ) : (
          (cell.priority_mean ?? 0).toFixed(3)
        )}
      </div>
      {cell.with_magnitude > 0 ? (
        <div className="mt-0.5 text-[10px] text-emerald-500/70">
          {cell.with_magnitude} disclosed exposure
          {cell.with_magnitude === 1 ? "" : "s"}
        </div>
      ) : null}
    </button>
  );
}

export function ChainMatrix({
  data,
  engine,
}: {
  data: ChainMatrixResponse;
  engine?: string;
}) {
  const [selected, setSelected] = useState<ChainCell | null>(null);

  const byChain = useMemo(() => {
    const map = new Map<string, ChainCell[]>();
    for (const c of data.cells) {
      const list = map.get(c.chain) ?? [];
      list.push(c);
      map.set(c.chain, list);
    }
    for (const list of map.values())
      list.sort((a, b) => a.layer_rank - b.layer_rank || a.layer.localeCompare(b.layer));
    return [...map.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [data.cells]);

  const totals = useMemo(() => {
    let members = 0;
    let magnitude = 0;
    for (const c of data.cells) {
      members += c.members;
      magnitude += c.with_magnitude;
    }
    return { members, magnitude };
  }, [data.cells]);

  return (
    <div className="p-6 text-zinc-200">
      <header className="mb-4">
        <h1 className="text-xl font-semibold">Industry chain matrix</h1>
        <p className="mt-1 text-sm text-zinc-400">
          Taxonomy <code className="text-zinc-300">{data.taxonomy_version}</code>,
          engine <code className="text-zinc-300">{data.engine_version ?? "none"}</code>.
          Layers read upstream → downstream.
        </p>
        {/* The finding, stated up front rather than discovered by hovering. */}
        <p className="mt-1 text-xs text-zinc-500">
          {totals.magnitude} of {totals.members} memberships carry a{" "}
          <span className="text-zinc-400">disclosed</span> economic magnitude.
          Everything else is a semantic placement, and the schema forbids it from
          carrying a number.
        </p>
      </header>

      {data.state !== "ok" ? (
        <div
          role="status"
          className="mb-4 rounded border border-amber-700/50 bg-amber-950/30 px-3 py-2 text-sm text-amber-200"
        >
          {data.state.replace(/_/g, " ")}
          {data.reason ? <span className="ml-2">{data.reason}</span> : null}
        </div>
      ) : null}

      <details className="mb-5 rounded border border-zinc-800 bg-zinc-900/40 px-3 py-2">
        <summary className="cursor-pointer text-xs uppercase tracking-wide text-zinc-400">
          What this matrix may not be read as
        </summary>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-zinc-400">
          {data.prohibited.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      </details>

      <div className="space-y-5">
        {byChain.map(([chain, cells]) => (
          <section key={chain}>
            <h2 className="mb-1.5 text-sm font-medium text-zinc-300">{chain}</h2>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
              {cells.map((c) => (
                <Cell key={cellKey(c)} cell={c} onSelect={setSelected} />
              ))}
            </div>
          </section>
        ))}
      </div>

      {selected ? (
        <aside className="mt-6 rounded border border-zinc-800 bg-zinc-900/50 p-4">
          <h3 className="text-sm font-medium">
            {selected.chain} · {selected.layer}
          </h3>
          <p className="mt-1 text-xs text-zinc-500">
            {selected.members} members, {selected.with_result} with a compatible
            result, {selected.with_magnitude} with a disclosed magnitude.
          </p>
          {selected.abstain_reason ? (
            <p className="mt-2 text-sm text-amber-300/80">
              {selected.abstain_reason}
            </p>
          ) : null}
          <a
            className="mt-3 inline-block text-sm text-zinc-300 underline-offset-2 hover:underline"
            href={`/chains/${encodeURIComponent(selected.chain)}?layer=${encodeURIComponent(
              selected.layer,
            )}${engine ? `&engine=${encodeURIComponent(engine)}` : ""}`}
          >
            Open the member list →
          </a>
        </aside>
      ) : null}
    </div>
  );
}
