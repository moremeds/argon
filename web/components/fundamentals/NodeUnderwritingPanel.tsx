import type { NodeUnderwritingRow } from "@/lib/api";

/**
 * The node's underwriting table: DIO, SBC/revenue, shares outstanding YoY,
 * each figure carrying the filed line items it was computed from.
 *
 * Three rules this component exists to hold:
 *
 * 1. **"Shares outstanding", never "diluted".** The source column is
 *    `common_stock_shares_outstanding` — BASIC period-end shares, 420/420
 *    coverage. Task 9 checked every `(statement, key)` pair in the store: no
 *    diluted or weighted-average share count exists at any tier. So this
 *    measures issuance and buyback, NOT option/RSU/convertible overhang, and
 *    the words "diluted" and "dilution" must never appear over it.
 * 2. **Provenance is visible, not only hoverable.** The filing date has its own
 *    column. The tooltip carries the raw filed values as well, but a tooltip is
 *    unreachable on touch and to a screen reader, and the requirement is
 *    traceability, not hover-discoverability.
 * 3. **`no_compatible_run` is not `no_coverage`.** Collapsing them turns "the
 *    job never ran" into "this company has no fundamentals" — a claim about a
 *    real business Argon is not entitled to make.
 *
 * It LISTS. There is no sort control, no rank column, and no score: cross-
 * sectional ordering measured INVERTED in this universe.
 */

const STATE_NOTE: Record<NodeUnderwritingRow["state"], string | null> = {
  ok: null,
  stale_run: "computed under a superseded engine version",
  // These two are deliberately worded so they can never be read as each other.
  no_compatible_run: "Argon has run nothing compatible for this name",
  no_coverage: "Argon holds no statements for this name",
  unsupported_capability: "the method refused to price this name",
  failed_run: "the last run for this name failed",
};

function provenance(row: NodeUnderwritingRow): string {
  return [
    row.ticker,
    `fiscal period ending ${row.period_end}`,
    `filed ${row.filing_published_at ?? "on an unrecorded date"}`,
    `inventory=${row.inventory_raw ?? "absent"}`,
    `cost_of_revenue=${row.cost_of_revenue_raw ?? "absent"}`,
    `stock_based_compensation=${row.sbc_raw ?? "absent"}`,
    `common_stock_shares_outstanding=${row.shares_outstanding_raw ?? "absent"}`,
  ].join(" · ");
}

function Figure({
  value,
  row,
  render,
}: {
  value: number | null;
  row: NodeUnderwritingRow;
  render: (v: number) => string;
}) {
  return (
    <span
      title={provenance(row)}
      className="tabular-nums text-xs text-zinc-200"
    >
      {value === null ? (
        <span className="text-zinc-600">na</span>
      ) : (
        render(value)
      )}
    </span>
  );
}

export function NodeUnderwritingPanel({
  rows,
  error,
}: {
  rows: NodeUnderwritingRow[];
  error?: string;
}) {
  // The length guard is the point. `[].every(...)` is TRUE, so without it an
  // empty table would print a sentence about what the filings say — a claim
  // drawn from no filings at all.
  const sbcAbsent =
    rows.length > 0 && rows.every((r) => r.sbc_to_revenue === null);

  // A failed request is not an empty chain. Rendering the empty-state copy for
  // it would turn "we could not ask" into "Argon holds nothing".
  if (error != null) {
    return (
      <section data-testid="node-underwriting" className="mt-6">
        <h2 className="text-sm font-semibold text-zinc-200">Underwriting</h2>
        <p className="mt-2 text-xs text-red-300" role="alert">
          The underwriting request failed: {error}
        </p>
      </section>
    );
  }

  return (
    <section data-testid="node-underwriting" className="mt-6">
      <h2 className="text-sm font-semibold text-zinc-200">Underwriting</h2>
      {rows.length === 0 ? (
        <p
          data-testid="node-underwriting-empty"
          className="mt-2 text-xs text-zinc-500"
        >
          No member of this chain carries an underwriting row. The chain exists;
          Argon holds nothing to underwrite it with.
        </p>
      ) : (
        <>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full min-w-[46rem] border-collapse text-left">
              <thead>
                <tr className="border-b border-zinc-800 text-[10px] uppercase tracking-wide text-zinc-500">
                  <th className="py-1 pr-4 font-normal">Ticker</th>
                  <th className="py-1 pr-4 font-normal">Period end</th>
                  <th className="py-1 pr-4 font-normal">Filed</th>
                  <th className="py-1 pr-4 font-normal">DIO (days)</th>
                  <th className="py-1 pr-4 font-normal">SBC / revenue</th>
                  {/* Never "diluted": this is the basic period-end count. */}
                  <th className="py-1 pr-4 font-normal">
                    Shares outstanding YoY
                  </th>
                  <th className="py-1 font-normal">State</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr
                    key={`${row.ticker}-${row.period_end}`}
                    data-testid={`underwriting-row-${row.ticker}`}
                    className="border-b border-zinc-900"
                  >
                    <td className="py-1.5 pr-4">
                      <a
                        href={`/stock/${row.ticker}`}
                        className="font-mono text-xs text-zinc-200 hover:underline"
                      >
                        {row.ticker}
                      </a>
                    </td>
                    <td className="py-1.5 pr-4 tabular-nums text-xs text-zinc-400">
                      {row.period_end}
                    </td>
                    {/* Visible, not only in the tooltip. */}
                    <td
                      data-testid={`filed-${row.ticker}`}
                      className="py-1.5 pr-4 tabular-nums text-xs text-zinc-400"
                    >
                      {row.filing_published_at ?? (
                        <span className="text-zinc-600">
                          no filing date held
                        </span>
                      )}
                    </td>
                    <td className="py-1.5 pr-4">
                      <Figure
                        value={row.dio}
                        row={row}
                        render={(v) => v.toFixed(1)}
                      />
                    </td>
                    <td className="py-1.5 pr-4">
                      <Figure
                        value={row.sbc_to_revenue}
                        row={row}
                        render={(v) => `${(v * 100).toFixed(1)}%`}
                      />
                    </td>
                    <td className="py-1.5 pr-4">
                      <Figure
                        value={row.shares_outstanding_yoy}
                        row={row}
                        render={(v) =>
                          `${v >= 0 ? "+" : ""}${(v * 100).toFixed(2)}%`
                        }
                      />
                    </td>
                    <td
                      data-testid={`state-${row.ticker}`}
                      className="py-1.5 text-[11px] text-zinc-500"
                    >
                      {STATE_NOTE[row.state] ?? "current"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-[11px] text-zinc-600">
            Every figure carries its filed line items — ticker, fiscal period,
            filing date, and the raw values — in its tooltip, and the filing
            date in its own column. Shares outstanding is the basic period-end
            count; the store holds no weighted-average share series at any tier.
          </p>
        </>
      )}
      {/* Section-level on purpose. Nested inside the non-empty branch, the
          `rows.length > 0` guard above would be dead code the JSX already
          enforced — and a guard nothing can violate is a guard no test can
          pin. Here it is the only thing standing between an empty node and a
          sentence about filings that do not exist. */}
      {sbcAbsent ? (
        <p data-testid="sbc-absent" className="mt-2 text-[11px] text-zinc-500">
          SBC / revenue is absent for every name in this node. The key itself is
          not missing: `stock_based_compensation` is present on the cash-flow
          statement for 419 of 420 tickers in the store, so this is a gap in
          these names&apos; ingested statements, not a capability the source
          lacks.
        </p>
      ) : null}
    </section>
  );
}
