/**
 * What this node page does NOT attempt (spec §4 close).
 *
 * Publishing the reason a number is absent is worth more trust than any number
 * that could be added in its place. Each entry below is stated as absent rather
 * than proxied — a proxy for capacity is not capacity, and a reader who is told
 * "no source" can go find one, while a reader handed a proxy cannot tell.
 */

/** Real underwriting inputs with no filings-derivable source. */
const NOT_ATTEMPTED: { name: string; why: string }[] = [
  {
    name: "ASP / mix",
    why: "no filing discloses per-unit price or unit mix; a revenue-over-units proxy would need a unit count nothing publishes",
  },
  {
    name: "Capacity",
    why: "wafer starts, fab or line capacity and utilisation are not filed line items",
  },
  {
    name: "Lead times",
    why: "quoted lead time is a commercial disclosure, absent from every statement Argon ingests",
  },
  {
    name: "Qualification status",
    why: "customer qualification is disclosed in commentary at best and is not derivable from the statements",
  },
];

export function NodeLimits() {
  return (
    <section data-testid="node-limits" className="mt-6">
      <h2 className="text-sm font-semibold text-zinc-200">
        What this page does not attempt
      </h2>

      <ul className="mt-2 space-y-1">
        {NOT_ATTEMPTED.map((item) => (
          <li
            key={item.name}
            data-testid={`node-limit-${item.name}`}
            className="text-xs text-zinc-400"
          >
            <span className="text-zinc-200">{item.name}</span>
            <span className="text-zinc-600"> — {item.why}</span>
          </li>
        ))}
      </ul>

      <h3 className="mt-4 text-[11px] uppercase tracking-wide text-zinc-500">
        What the store was probed for
      </h3>
      <ul
        data-testid="node-limits-probe"
        className="mt-1 space-y-1 text-xs text-zinc-400"
      >
        <li>
          <span className="text-zinc-200">
            Stock-based compensation — present.
          </span>{" "}
          <span className="text-zinc-600">
            `stock_based_compensation` on the cash-flow statement, 419 of 420
            tickers.
          </span>
        </li>
        <li>
          <span className="text-zinc-200">
            Diluted / weighted-average share count — not present in the ingested
            statements.
          </span>{" "}
          <span className="text-zinc-600">
            Every (statement, key) pair in the store was checked; no such field
            exists at any tier. The table above therefore reports BASIC
            period-end shares outstanding, which measures issuance and buyback
            and says nothing about option, RSU or convertible overhang.
          </span>
        </li>
      </ul>

      <p
        data-testid="node-limits-alias-caveat"
        className="mt-4 text-xs text-amber-300/80"
      >
        Two exposure magnitudes above ride open alias questions — changing a
        rule changes these numbers.
      </p>
    </section>
  );
}
