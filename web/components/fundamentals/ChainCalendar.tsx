import {
  ImpliedMove,
  SessionBadge,
} from "@/components/fundamentals/NodeCalendarStrip";
import type { DeskCalendarResponse, DeskCalendarRow } from "@/lib/api";

/**
 * The section's calendar, chain-ordered: what prints next across every node.
 *
 * IT RENDERS THE RESPONSE'S ORDER AND NEVER RE-SORTS.
 * The API orders by report_date then `layer_rank` — upstream to downstream —
 * and that second key is meaning this component cannot reconstruct from the
 * rows alone. Sorting client-side by date would silently discard the chain
 * position the desk exists to show. (The delta rail does the opposite and
 * sorts explicitly; there the key IS on every row.)
 *
 * `SessionBadge` and `ImpliedMove` are imported rather than re-implemented.
 * Those two branches encode the honest-absence rules a full fix round was
 * spent getting right — a null implied move is "not covered", never a dash;
 * a null session is a real third value with a visible badge. A second copy
 * would let one of them drift, and the drifted copy would be a lie about
 * coverage rather than a cosmetic difference.
 */

/** `spot_percentile` is a YIELD percentile: 0.80 means CHEAP against this
 *  name's own history. A bare "0.80" in a row of prices reads as the exact
 *  opposite, so the number never reaches the screen without its direction
 *  attached. Same inversion `rankPhrase` guards on the value scanner. */
function ownHistoryPhrase(pct: number): string {
  return `Cheaper than ${Math.round(pct * 100)}% of its own history`;
}

function Percentile({ row }: { row: DeskCalendarRow }) {
  if (row.spot_percentile === null) {
    // WHY the percentile is missing is a different answer from "it is
    // missing", and the six states distinguish "the job never ran" from
    // "this company has no coverage" — a claim about a real business.
    return (
      <span
        data-testid="percentile-state"
        title="No own-history valuation percentile stands for this name; the state names which kind of absence it is."
        className="text-[11px] text-zinc-500"
      >
        {row.percentile_state}
      </span>
    );
  }
  return (
    <span
      data-testid="own-history-phrase"
      className="text-[11px] text-zinc-400"
      title="A yield percentile: higher means cheaper against this name's own history, never against its peers."
    >
      {ownHistoryPhrase(row.spot_percentile)}
    </span>
  );
}

export function ChainCalendar({
  data,
  error,
}: {
  data: DeskCalendarResponse | null;
  error?: string;
}) {
  if (error != null) {
    return (
      <section data-testid="desk-calendar" className="mt-6">
        <h2 className="text-sm font-semibold text-zinc-200">Next prints</h2>
        <p className="mt-2 text-xs text-red-300" role="alert">
          The calendar request failed: {error}
        </p>
      </section>
    );
  }
  const rows = data?.rows ?? [];
  return (
    <section data-testid="desk-calendar" className="mt-6">
      <div className="flex flex-wrap items-baseline gap-2">
        <h2 className="text-sm font-semibold text-zinc-200">Next prints</h2>
        {data ? (
          <span className="text-[11px] text-zinc-600">
            {data.section} · as of {data.as_of} · upstream to downstream
          </span>
        ) : null}
      </div>
      {rows.length === 0 ? (
        <p
          data-testid="desk-calendar-empty"
          className="mt-2 text-xs text-zinc-500"
        >
          No upcoming print is held for any member of this section.
        </p>
      ) : (
        <ul className="mt-2 divide-y divide-zinc-900 border-y border-zinc-900">
          {rows.map((row) => (
            <li
              key={`${row.ticker}-${row.report_date}-${row.chain}-${row.layer}`}
              data-testid={`desk-calendar-row-${row.ticker}`}
              className="flex flex-wrap items-center gap-x-4 gap-y-1 py-2"
            >
              <a
                href={`/stock/${row.ticker}`}
                className="w-16 font-mono text-sm text-zinc-200 hover:underline"
              >
                {row.ticker}
              </a>
              <span className="w-24 tabular-nums text-xs text-zinc-400">
                {row.report_date}
              </span>
              <SessionBadge session={row.session} />
              <span className="w-44 truncate text-[10px] uppercase tracking-wide text-zinc-600">
                {row.chain} · {row.layer}
              </span>
              <ImpliedMove row={row} />
              <Percentile row={row} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
