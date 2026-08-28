/**
 * Hyperscaler capex, deliberately demoted to a copy-only strip.
 *
 * THIS COMPONENT HAS NO DATA SOURCE, NO FETCHER AND NO MODEL FIELD, AND THAT
 * IS THE DELIVERABLE. Hyperscaler capex is on every sell-side deck in the
 * sector; a number everyone already has cannot be where this desk's edge comes
 * from. Building a data path for it would re-promote the exact figure the spec
 * demoted — the strip would then look like a signal because it cost something
 * to compute.
 *
 * The sign inversion is the part worth saying out loud, because it is the part
 * that gets read backwards: for the layers that SPEND the capex it is a cost
 * line, not evidence of demand. Rising capex at L4/L5 is margin pressure
 * arriving, and reading it as bullish for the spender inverts its meaning.
 *
 * The filed figures live per name, on the stock pages, where they carry their
 * own filing dates. If a later phase wants the number on the desk itself, that
 * is a new decision with a new argument — not this strip growing a fetcher.
 */

const SPENDERS = ["MSFT", "AMZN", "GOOGL", "META"];

export function CapexContextStrip() {
  return (
    <section
      data-testid="capex-context"
      className="mt-6 rounded border border-zinc-800 bg-zinc-950/40 p-3"
    >
      <h2 className="text-sm font-semibold text-zinc-200">Capex — context</h2>
      <p className="mt-1 text-xs text-zinc-400">
        Hyperscaler capex is the most widely circulated number in this sector,
        which is why the desk keeps it as context rather than treating it as
        edge. For the names that spend it, rising capex is a{" "}
        <strong className="text-zinc-200">cost line, not demand</strong> — it
        reaches the income statement as depreciation. Read on this desk it is{" "}
        <strong className="text-zinc-200">context, not edge</strong>.
      </p>
      <p className="mt-2 text-[11px] text-zinc-600">
        The filed figures sit on each spender&apos;s own page, with the filing
        date attached:{" "}
        {SPENDERS.map((t, i) => (
          <span key={t}>
            {i > 0 ? " · " : ""}
            <a
              href={`/stock/${t}`}
              className="font-mono text-zinc-400 hover:underline"
            >
              {t}
            </a>
          </span>
        ))}
      </p>
    </section>
  );
}
