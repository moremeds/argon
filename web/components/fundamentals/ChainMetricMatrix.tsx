import type { ChainMetricCell, DeskMatrixResponse, MemberDot } from "@/lib/api";

/**
 * chain × metric. Medians over per-name dots, and four rules that are each a
 * measured finding rather than a style choice:
 *
 * 1. THE MEDIAN IS UNWEIGHTED. A revenue-weighted "optical" gross margin is
 *    the largest member's margin wearing the chain's name.
 * 2. `valuation_percentile` GETS NO MEDIAN, ever. Own-history percentiles are
 *    NAME facts; an aggregate over them is the "chain percentile distribution"
 *    the spec bans, because own-history value measured real (within-ticker IC
 *    +0.0744, t 5.77) while cross-sectional value measured INVERTED in the
 *    same universe. The dots still render: the name-level facts are real.
 * 3. TWO COHORTS NEVER MERGE. `fundamental_scores.as_of` is a cross-section
 *    IDENTIFIER, not a freshness stamp, and the cohort effect measured 1.9x.
 *    When members straddle two buckets that is reporting season, and a merged
 *    median compares names that were never in the same peer group. The median
 *    the API sends belongs to the dominant cohort and renders UNDER that
 *    label — never floating above both, where it reads as their average.
 * 4. AN EMPTY CELL STATES WHICH ABSTENTION IT IS. `no_compatible_run` ("the
 *    job never ran") and `no_coverage` ("this company has no fundamentals")
 *    are different claims, and the second is a statement about a real business
 *    Argon is not entitled to make. A blank cell makes it anyway.
 *
 * Nothing here sorts by any metric. `chains` arrives ordered by minimum
 * `layer_rank`, ties alphabetically, and that is the order rendered.
 */

const METRICS = ["rev_yoy", "gross_margin", "valuation_percentile"] as const;

const METRIC_LABEL: Record<string, string> = {
  rev_yoy: "Revenue YoY",
  gross_margin: "Gross margin",
  valuation_percentile: "Own-history value",
};

function pct(v: number): string {
  return `${(v * 100).toFixed(1)}%`;
}

function Median({ value }: { value: number }) {
  return (
    <span
      data-testid="cell-median"
      className="tabular-nums text-sm text-zinc-100"
      title="Unweighted median of the member values — never revenue-weighted."
    >
      {pct(value)}
    </span>
  );
}

/** Hand-rolled SVG (no chart library). One dot per DISTINCT ticker; a name
 *  with no figure draws no dot rather than a dot at zero, which would place it
 *  wherever the reader takes zero to mean. */
function Dots({ dots }: { dots: MemberDot[] }) {
  const withValue = dots.filter((d) => d.value !== null);
  if (withValue.length === 0) return null;
  const values = withValue.map((d) => d.value as number);
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const span = hi - lo || 1;
  const w = 120;
  return (
    <svg
      role="img"
      aria-label={`${withValue.length} member values`}
      width={w}
      height={14}
      viewBox={`0 0 ${w} 14`}
      className="mt-1"
    >
      {withValue.map((d) => (
        <circle
          key={d.ticker}
          data-testid={`cell-dot-${d.ticker}`}
          cx={6 + (((d.value as number) - lo) / span) * (w - 12)}
          cy={7}
          r={3}
          fill="var(--accent-bg, #60a5fa)"
          opacity={0.85}
        >
          {/* ONE expression, one text node. Adjacent JSX text children inside
              an SVG <title> serialize differently on the server than they
              hydrate on the client, which React reports as a hydration
              mismatch and then re-renders the whole tree over. */}
          <title>
            {`${d.ticker}: ${pct(d.value as number)}${
              d.knowledge_date_estimated === true
                ? " (knowledge date estimated, not filed)"
                : ""
            }`}
          </title>
        </circle>
      ))}
    </svg>
  );
}

function CoverageMissing({ tickers }: { tickers: string[] }) {
  if (tickers.length === 0) return null;
  return (
    <p
      data-testid="cell-coverage-missing"
      className="mt-1 text-[10px] text-zinc-600"
      title="Named, never counted: 'missing: COHR' is actionable, '12/18' is decoration."
    >
      no value: {tickers.join(", ")}
    </p>
  );
}

function Cell({ cell }: { cell: ChainMetricCell }) {
  const hasAnyValue = cell.dots.some((d) => d.value !== null);
  const states = [...new Set(cell.dots.map((d) => d.state))];
  const cohorts = cell.cohorts;
  const isPercentile = cell.metric === "valuation_percentile";

  return (
    <td
      data-testid={`matrix-cell-${cell.chain}-${cell.metric}`}
      className="border border-zinc-900 px-2 py-2 align-top"
    >
      {!hasAnyValue ? (
        <div
          data-testid="cell-abstention"
          className="rounded border border-dashed border-zinc-700 bg-[repeating-linear-gradient(45deg,transparent,transparent_4px,rgba(255,255,255,0.03)_4px,rgba(255,255,255,0.03)_8px)] px-2 py-1 text-[10px] text-zinc-500"
          title="No member carries this metric. The state names which kind of absence this is."
        >
          {states.join(" · ")}
        </div>
      ) : cohorts.length > 1 ? (
        <div className="space-y-2">
          {cohorts.map((c) => (
            <div
              // Keyed and identified by as_of, NOT by label alone: `label` is
              // 'reported' for the newest bucket and 'awaiting' for EVERY older
              // one, so a chain mid-reporting-season legitimately carries two or
              // more `awaiting` cohorts (measured: Cybersecurity/rev_yoy came
              // back ['reported','awaiting','awaiting'] on 2026-08-28). Keying
              // on the label collides, and a testid that matches two elements
              // makes `getByTestId` throw against real data while passing on
              // any fixture that happens to hold one of each.
              key={`${c.label}-${c.as_of}`}
              data-testid={`cohort-${c.label}-${c.as_of}`}
              className="rounded border border-zinc-800 px-2 py-1"
            >
              <div className="flex items-baseline gap-2">
                <span className="text-[10px] uppercase tracking-wide text-zinc-500">
                  {c.label} · {c.as_of}
                </span>
                {/* The median the API computed belongs to the dominant
                    cross-section and is shown only there. */}
                {c.label === "reported" && cell.median !== null ? (
                  <Median value={cell.median} />
                ) : null}
              </div>
              <p className="font-mono text-[11px] text-zinc-400">
                {c.tickers.join(" ")}
              </p>
            </div>
          ))}
          <Dots dots={cell.dots} />
        </div>
      ) : (
        <div>
          {isPercentile ? (
            <p
              data-testid="cell-name-level-caption"
              className="text-[10px] text-zinc-500"
            >
              name-level positions in each name&apos;s own history — not a chain
              property
            </p>
          ) : cell.median !== null ? (
            <Median value={cell.median} />
          ) : null}
          <Dots dots={cell.dots} />
        </div>
      )}
      <CoverageMissing tickers={cell.coverage_missing} />
    </td>
  );
}

export function ChainMetricMatrix({
  data,
  error,
}: {
  data: DeskMatrixResponse | null;
  error?: string;
}) {
  if (error != null) {
    return (
      <section data-testid="desk-matrix" className="mt-6">
        <h2 className="text-sm font-semibold text-zinc-200">Chain × metric</h2>
        <p className="mt-2 text-xs text-red-300" role="alert">
          The matrix request failed: {error}
        </p>
      </section>
    );
  }
  const chains = data?.chains ?? [];
  const byKey = new Map(
    (data?.cells ?? []).map((c) => [`${c.chain}|${c.metric}`, c]),
  );
  return (
    <section data-testid="desk-matrix" className="mt-6">
      <h2 className="text-sm font-semibold text-zinc-200">Chain × metric</h2>
      {chains.length === 0 ? (
        <p
          data-testid="desk-matrix-empty"
          className="mt-2 text-xs text-zinc-500"
        >
          This section holds no chain.
        </p>
      ) : (
        <div className="mt-2 overflow-x-auto">
          <table className="w-full border-collapse text-xs">
            <thead>
              <tr>
                <th className="px-2 py-1 text-left text-[10px] uppercase tracking-wide text-zinc-600">
                  chain
                </th>
                {METRICS.map((m) => (
                  <th
                    key={m}
                    className="px-2 py-1 text-left text-[10px] uppercase tracking-wide text-zinc-600"
                  >
                    {METRIC_LABEL[m]}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {chains.map((chain) => (
                <tr key={chain}>
                  <th className="border border-zinc-900 px-2 py-2 text-left align-top font-mono text-[11px] font-normal text-zinc-300">
                    {chain}
                  </th>
                  {METRICS.map((m) => {
                    const c = byKey.get(`${chain}|${m}`);
                    return c ? (
                      <Cell key={m} cell={c} />
                    ) : (
                      <td
                        key={m}
                        data-testid={`matrix-cell-${chain}-${m}`}
                        className="border border-zinc-900 px-2 py-2 align-top"
                      >
                        <div
                          data-testid="cell-abstention"
                          className="rounded border border-dashed border-zinc-700 px-2 py-1 text-[10px] text-zinc-500"
                        >
                          no cell computed
                        </div>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
