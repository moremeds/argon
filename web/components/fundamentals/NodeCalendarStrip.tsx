import type { DeskCalendarResponse, DeskCalendarRow } from "@/lib/api";

/**
 * The node's live calendar strip: what prints next, inside this chain.
 *
 * Every column here is an absence that had to survive to the screen, and each
 * one was a shipped bug at some layer of this branch:
 *
 * - `implied_move_pct === null` means NOT COVERED for THIS print — the nightly
 *   snapshot only reaches prints inside its lookahead window, and a snapshot
 *   computed for an earlier print is never carried forward. It renders as the
 *   words "not covered". Never 0, never blank, never a dash: `fmtPct` answers
 *   "—" for null and a dash in a percent column reads as zero.
 * - `session === null` is a REAL third value, not missing data: the ~2% of
 *   names UW reports as `report_time: "unknown"` appear in neither classified
 *   slot, permanently. The row stays, and the unknown is a visible badge —
 *   hiding the row or guessing a side are both lies.
 * - `reactions.length === 0` means no reaction history is HELD. That is not
 *   "the stock did not move", so it must not render like a flat dot.
 *
 * Nothing here sorts, ranks, or scores. The response order is the desk's
 * reading order (upstream → downstream by `layer_rank`) and this component
 * renders it as given.
 */

const SESSION_LABEL: Record<string, string> = {
  premarket: "PRE",
  afterhours: "AFT",
};

function SessionBadge({ session }: { session: string | null }) {
  if (session === null) {
    // Visible, never hidden: an unclassified print is a fact about UW's
    // calendar, and it stays on the row that carries it.
    return (
      <span
        data-testid="session-unknown"
        title="UW never classified this print's session; Argon does not guess one."
        className="rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-amber-300"
      >
        ? session unknown
      </span>
    );
  }
  return (
    <span
      data-testid={`session-${session}`}
      className="rounded border border-zinc-700 bg-zinc-800/60 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-zinc-300"
    >
      {SESSION_LABEL[session] ?? session}
    </span>
  );
}

function ImpliedMove({ row }: { row: DeskCalendarRow }) {
  if (row.implied_move_pct === null) {
    return (
      <span
        data-testid="implied-move-not-covered"
        title="No implied-move snapshot covers this print. The nightly job only reaches prints inside its lookahead window, and an earlier print's snapshot is never carried forward onto a later one."
        className="text-[11px] text-zinc-500"
      >
        not covered
      </span>
    );
  }
  return (
    <span
      data-testid="implied-move"
      title={`computed on ${row.implied_move_asof ?? "an unrecorded date"}`}
      className="tabular-nums text-[12px] text-zinc-200"
    >
      ±{(row.implied_move_pct * 100).toFixed(1)}%
      <span className="ml-1 text-[10px] text-zinc-600">
        as of {row.implied_move_asof}
      </span>
    </span>
  );
}

/** Hand-rolled SVG (no chart library). Newest print leftmost — the API orders
 *  `reactions` newest-first and this preserves that order rather than
 *  re-sorting it into a time axis it never claimed to be. */
function ReactionDots({ reactions }: { reactions: number[] }) {
  if (reactions.length === 0) {
    return (
      <span
        data-testid="reactions-absent"
        title="Argon holds no realised reaction for this name. This is an absence of history, not a measurement of zero."
        className="text-[11px] text-zinc-500"
      >
        no reaction history held
      </span>
    );
  }
  const step = 18;
  return (
    <svg
      data-testid="reactions"
      role="img"
      aria-label={`last ${reactions.length} realised print moves, newest first`}
      width={reactions.length * step}
      height={16}
      viewBox={`0 0 ${reactions.length * step} 16`}
    >
      <title>
        {reactions.map((r) => `${(r * 100).toFixed(2)}%`).join(", ")} — newest
        first
      </title>
      {reactions.map((r, i) => (
        <circle
          key={i}
          cx={step / 2 + i * step}
          cy={8}
          // A 0.00% print is a real measurement and must still draw a mark;
          // the floor keeps it visible instead of collapsing it to nothing.
          r={Math.min(6, 2 + Math.abs(r) * 40)}
          fill={
            r >= 0 ? "var(--positive, #34d399)" : "var(--negative, #f87171)"
          }
          opacity={0.85}
        />
      ))}
    </svg>
  );
}

export function NodeCalendarStrip({
  data,
  error,
}: {
  data: DeskCalendarResponse | null;
  error?: string;
}) {
  if (error != null) {
    return (
      <section data-testid="node-calendar" className="mt-6">
        <h2 className="text-sm font-semibold text-zinc-200">Next prints</h2>
        <p className="mt-2 text-xs text-red-300" role="alert">
          The calendar request failed: {error}
        </p>
      </section>
    );
  }
  const rows = data?.rows ?? [];
  return (
    <section data-testid="node-calendar" className="mt-6">
      <div className="flex flex-wrap items-baseline gap-2">
        <h2 className="text-sm font-semibold text-zinc-200">Next prints</h2>
        {data ? (
          <span className="text-[11px] text-zinc-600">
            {data.section} · as of {data.as_of}
          </span>
        ) : null}
      </div>
      {rows.length === 0 ? (
        <p
          data-testid="node-calendar-empty"
          className="mt-2 text-xs text-zinc-500"
        >
          No upcoming print is held for any member of this chain. This node
          exists and its calendar is empty — that is not the same as the chain
          being unknown, which answers 404.
        </p>
      ) : (
        <ul className="mt-2 divide-y divide-zinc-900 border-y border-zinc-900">
          {rows.map((row) => (
            <li
              key={`${row.ticker}-${row.report_date}-${row.layer}`}
              data-testid={`calendar-row-${row.ticker}`}
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
              <span className="w-40 text-[10px] uppercase tracking-wide text-zinc-600">
                {row.layer}
              </span>
              <ImpliedMove row={row} />
              <ReactionDots reactions={row.reactions} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
