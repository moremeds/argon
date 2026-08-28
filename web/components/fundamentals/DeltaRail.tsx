import type { DeltaRailEvent, DeltaRailResponse } from "@/lib/api";

/**
 * What changed since the operator last looked.
 *
 * TWO CLOCKS, AND THE RAIL IS ORDERED BY THE SECOND ONE.
 * `occurred_at` is when the thing happened in the world; `first_known_at` is
 * when Argon learned it. "What changed since I last looked" is a question
 * about the reader's knowledge, not the world's history, so the rail sorts on
 * `first_known_at` — and both dates render on every row, because a filing that
 * happened in June and was indexed in August is two different facts and
 * showing one of them invents a timeline.
 *
 * The sort here is deliberate rather than trusting the response order: the API
 * orders DESC, but this component states the invariant it depends on instead
 * of inheriting it silently. (The calendar does the opposite and preserves the
 * server's order — there the order carries meaning this component cannot
 * reconstruct, upstream to downstream.)
 */
function EventRow({ event }: { event: DeltaRailEvent }) {
  const also =
    typeof event.detail?.also === "string" ? event.detail.also : null;
  return (
    <li
      data-testid={`delta-event-${event.ticker}`}
      className="flex flex-wrap items-baseline gap-x-3 gap-y-1 py-2"
    >
      <span
        data-testid="first-known-at"
        title="When Argon first knew this. The rail's ordering key."
        className="w-24 tabular-nums text-xs text-zinc-300"
      >
        {event.first_known_at}
      </span>
      <a
        href={`/stock/${event.ticker}`}
        className="w-16 font-mono text-sm text-zinc-200 hover:underline"
      >
        {event.ticker}
      </a>
      <span className="text-[10px] uppercase tracking-wide text-zinc-600">
        {event.event_class}
      </span>
      <span className="text-xs text-zinc-300">{event.title}</span>
      <span
        data-testid="occurred-at"
        title="When it happened in the world. Not the same clock as the one this rail is ordered by."
        className="tabular-nums text-[10px] text-zinc-600"
      >
        occurred {event.occurred_at}
      </span>
      {also === null ? null : (
        // A second class fired for the same fact and was collapsed into this
        // entry. Naming it keeps the collapse visible instead of quietly
        // dropping an event the ledger holds.
        <span
          data-testid="delta-also"
          className="rounded border border-zinc-700 px-1.5 py-0.5 text-[10px] text-zinc-400"
        >
          also {also}
        </span>
      )}
    </li>
  );
}

export function DeltaRail({
  data,
  error,
}: {
  data: DeltaRailResponse | null;
  error?: string;
}) {
  if (error != null) {
    return (
      <section data-testid="delta-rail" className="mt-6">
        <h2 className="text-sm font-semibold text-zinc-200">
          Since you looked
        </h2>
        <p className="mt-2 text-xs text-red-300" role="alert">
          The delta request failed: {error}
        </p>
      </section>
    );
  }
  const events = [...(data?.events ?? [])].sort((a, b) =>
    a.first_known_at < b.first_known_at ? 1 : -1,
  );
  return (
    <section data-testid="delta-rail" className="mt-6">
      <div className="flex flex-wrap items-baseline gap-2">
        <h2 className="text-sm font-semibold text-zinc-200">
          Since you looked
        </h2>
        {data ? (
          <span className="text-[11px] text-zinc-600">
            events Argon first knew on or after {data.since}
          </span>
        ) : null}
      </div>
      {events.length === 0 ? (
        <p
          data-testid="delta-rail-empty"
          className="mt-2 text-xs text-zinc-500"
        >
          Argon learned nothing new about this section in the window. That is an
          empty window, not an empty ledger.
        </p>
      ) : (
        <ul className="mt-2 divide-y divide-zinc-900 border-y border-zinc-900">
          {events.map((e) => (
            <EventRow
              key={`${e.ticker}-${e.event_class}-${e.occurred_at}`}
              event={e}
            />
          ))}
        </ul>
      )}
    </section>
  );
}
