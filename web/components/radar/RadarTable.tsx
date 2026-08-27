"use client";

import { useMemo, useState } from "react";
import type { RadarDimension, RadarResponse, RadarRow } from "@/lib/api";

/** The Radar's visual language is deliberately NEUTRAL.
 *
 *  This table orders names for analyst ATTENTION — the claim registry caps it at
 *  `research_priority`, and the measured basis is a rank IC of 0.039 that earns
 *  nothing as a book. Green/red, arrows, or a "score" gauge would all invite the
 *  buy/sell reading the registry explicitly prohibits. Rank position and a bar
 *  whose only meaning is "further right = looked at earlier" is the strongest
 *  visual claim the evidence supports.
 */

const DIMENSION_LABEL: Record<string, string> = {
  growth: "Growth",
  operating_quality: "Op. quality",
  balance_sheet: "Balance sheet",
  cash_conversion: "Cash conv.",
  capital_efficiency: "Capital eff.",
  valuation: "Valuation",
  evidence_quality: "Evidence",
  priority: "Priority",
};

/** Authorities that may contribute to the ordering. Everything else renders as
 *  context — a descriptive dimension shown beside a sorted column would read as
 *  part of the sort. */
const ORDERING_AUTHORITY = "research_priority";

function fmt(v: number | null | undefined, digits = 2): string {
  return v == null ? "na" : v.toFixed(digits);
}

function DimensionCell({ dim }: { dim: RadarDimension }) {
  const descriptive = dim.authority !== ORDERING_AUTHORITY;
  const partial =
    dim.inputs_expected > 0 && dim.inputs_present < dim.inputs_expected;
  return (
    <td
      className={`px-2 py-1 text-right tabular-nums ${
        descriptive ? "text-zinc-500" : "text-zinc-200"
      }`}
      title={`${dim.dimension} · ${dim.authority} · ${dim.inputs_present}/${dim.inputs_expected} inputs`}
    >
      {fmt(dim.value)}
      {partial ? (
        <span className="ml-1 text-[10px] text-amber-500/80">
          {dim.inputs_present}/{dim.inputs_expected}
        </span>
      ) : null}
    </td>
  );
}

function StateNotice({ data }: { data: RadarResponse }) {
  if (data.state === "ok") return null;
  return (
    <div
      role="status"
      className="mb-4 rounded border border-amber-700/50 bg-amber-950/30 px-3 py-2 text-sm text-amber-200"
    >
      <span className="font-medium">{data.state.replace(/_/g, " ")}</span>
      {data.reason ? <span className="ml-2 text-amber-200/80">{data.reason}</span> : null}
    </div>
  );
}

export function RadarTable({ data }: { data: RadarResponse }) {
  const [showExtreme, setShowExtreme] = useState(true);

  const dimensionOrder = useMemo(() => {
    const seen = new Set<string>();
    for (const row of data.rows)
      for (const d of row.dimensions) seen.add(d.dimension);
    return [
      "growth",
      "balance_sheet",
      "cash_conversion",
      "capital_efficiency",
      "operating_quality",
      "valuation",
      "evidence_quality",
    ].filter((d) => seen.has(d));
  }, [data.rows]);

  const rows: RadarRow[] = useMemo(
    () =>
      showExtreme
        ? data.rows
        : data.rows.filter((r) => (r.extreme_dimensions ?? []).length === 0),
    [data.rows, showExtreme],
  );

  return (
    <div className="p-6 text-zinc-200">
      <header className="mb-4">
        <h1 className="text-xl font-semibold">Fundamental PM Research Radar</h1>
        <p className="mt-1 text-sm text-zinc-400">
          Attention routing over{" "}
          <span className="tabular-nums">{data.scope.names}</span> names in tier{" "}
          <code className="text-zinc-300">{data.scope.tier}</code>. Ordering is{" "}
          <code className="text-zinc-300">{data.ordering}</code>, permitted at{" "}
          <span className="text-zinc-300">{data.ordering_authority}</span>.
        </p>
        {/* The denominator, stated. A table of 400 rows over a 449-name universe
            is a different object from a complete one, and the difference is
            invisible unless it is written down. */}
        <p className="mt-1 text-xs text-zinc-500">
          {data.scope.names_without_result} of {data.scope.names} names have no
          compatible result and are absent from this table. Engine{" "}
          <code>{data.scope.engine_version ?? "none"}</code>, evidence policy{" "}
          <code>{data.scope.evidence_policy}</code>.
        </p>
      </header>

      <StateNotice data={data} />

      {data.prohibited.length ? (
        <details className="mb-4 rounded border border-zinc-800 bg-zinc-900/40 px-3 py-2">
          <summary className="cursor-pointer text-xs uppercase tracking-wide text-zinc-400">
            What this ordering may not be read as
          </summary>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-zinc-400">
            {data.prohibited.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </details>
      ) : null}

      <label className="mb-3 inline-flex items-center gap-2 text-xs text-zinc-400">
        <input
          type="checkbox"
          checked={showExtreme}
          onChange={(e) => setShowExtreme(e.target.checked)}
          className="accent-zinc-500"
        />
        Show names whose rank is driven by an extreme (|z| &gt; 10) dimension
      </label>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[860px] border-collapse text-sm">
          <thead>
            <tr className="border-b border-zinc-800 text-xs uppercase tracking-wide text-zinc-500">
              <th className="px-2 py-2 text-left">#</th>
              <th className="px-2 py-2 text-left">Ticker</th>
              <th className="px-2 py-2 text-left">Type</th>
              <th className="px-2 py-2 text-right">Priority</th>
              <th className="px-2 py-2 text-right">Dims</th>
              {dimensionOrder.map((d) => (
                <th key={d} className="px-2 py-2 text-right">
                  {DIMENSION_LABEL[d] ?? d}
                </th>
              ))}
              <th className="px-2 py-2 text-left">Notes</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => {
              const byDim = new Map(row.dimensions.map((d) => [d.dimension, d]));
              const extreme = row.extreme_dimensions ?? [];
              return (
                <tr
                  key={row.ticker}
                  className="border-b border-zinc-900 hover:bg-zinc-900/40"
                >
                  <td className="px-2 py-1 tabular-nums text-zinc-600">{i + 1}</td>
                  <td className="px-2 py-1">
                    <a
                      className="text-zinc-100 underline-offset-2 hover:underline"
                      href={`/stock/${row.ticker}`}
                    >
                      {row.ticker}
                    </a>
                  </td>
                  <td className="px-2 py-1 text-zinc-500">
                    {row.company_type ?? "—"}
                  </td>
                  <td className="px-2 py-1 text-right tabular-nums">
                    {/* A refused aggregate says so. Rendering it as 0.00 would put
                        it in the middle of the distribution, which is a claim. */}
                    {row.priority == null ? (
                      <span className="text-zinc-600">refused</span>
                    ) : (
                      fmt(row.priority)
                    )}
                  </td>
                  <td className="px-2 py-1 text-right tabular-nums text-zinc-500">
                    {row.dimensions_present}/{row.dimensions_expected}
                  </td>
                  {dimensionOrder.map((d) => {
                    const dim = byDim.get(d);
                    return dim ? (
                      <DimensionCell key={d} dim={dim} />
                    ) : (
                      <td key={d} className="px-2 py-1 text-right text-zinc-700">
                        na
                      </td>
                    );
                  })}
                  <td className="px-2 py-1 text-xs text-zinc-500">
                    {extreme.length ? (
                      <span
                        className="text-amber-500/90"
                        title={`Rank driven by a tail reading in: ${extreme.join(", ")}`}
                      >
                        extreme: {extreme.join(", ")}
                      </span>
                    ) : null}
                    {row.missing_dimensions.length ? (
                      <span className="ml-2 text-zinc-600">
                        missing: {row.missing_dimensions.join(", ")}
                      </span>
                    ) : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {rows.length === 0 ? (
        <p className="mt-6 text-sm text-zinc-500">
          No rows under this scope. That is a statement about what Argon has
          computed, not about these companies.
        </p>
      ) : null}
    </div>
  );
}
