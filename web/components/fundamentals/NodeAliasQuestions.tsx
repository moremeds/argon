/**
 * The two open alias questions (spec §8-1), surfaced rather than silently
 * corrected.
 *
 * Both change a PUBLISHED number, which is why neither has been decided
 * quietly: an alias rule is an operator decision, and until it is made the
 * question belongs on the page beside the number it governs.
 *
 * The copy is static — it states the question, not an answer. What is NOT
 * static is whether the stored report actually backs it: when the exposure
 * block is unavailable (no published report, or a report without that block)
 * this component says so instead of rendering the copy as though the
 * `is_member` flags had been read. Asserting a membership fact we did not read
 * is the same failure as rendering a null as a zero.
 */

export type AliasExposure = {
  ticker: string;
  magnitude: number | null;
  basis: string | null;
  is_member: boolean;
};

/** The names carrying an open question, with the question itself. */
const QUESTIONS: { ticker: string; question: string }[] = [
  {
    ticker: "APH",
    question:
      "The 61.5% magnitude rides an over-broad `communicationssolutions` alias on a name nobody placed in this chain. Keeping the alias keeps the published 61.5%; narrowing it removes the magnitude from this node entirely.",
  },
  {
    ticker: "CIEN",
    question:
      "The 1.5% mapped here is CIEN's SMALLEST disclosed segment, while the same filing discloses better tags — 81% on the segment axis, 70% on the product axis. Re-tagging replaces a published 1.5% with a materially different number.",
  },
];

function Reading({ found }: { found: AliasExposure | undefined }) {
  if (found === undefined) {
    return (
      <span className="text-[11px] text-zinc-600">
        the published report carries no exposure row for this name
      </span>
    );
  }
  return (
    <span className="text-[11px] text-zinc-500">
      published:{" "}
      <span className="tabular-nums text-zinc-300">
        {found.magnitude === null
          ? "no magnitude"
          : `${(found.magnitude * 100).toFixed(1)}%`}
      </span>
      {found.basis ? ` on ${found.basis}` : ""} ·{" "}
      {found.is_member
        ? "a member of this chain"
        : "NOT a member of this chain"}
    </span>
  );
}

export function NodeAliasQuestions({
  exposures,
}: {
  exposures: AliasExposure[] | null;
}) {
  return (
    <section data-testid="node-alias-questions" className="mt-6">
      <h2 className="text-sm font-semibold text-zinc-200">
        Open alias questions
      </h2>
      <p className="mt-1 text-[11px] text-zinc-500">
        Changing an alias rule changes a published number. These two are open
        operator decisions and stay visible here until they are made.
      </p>
      {exposures === null ? (
        <p
          data-testid="alias-no-report"
          className="mt-2 text-[11px] text-amber-300/80"
        >
          No published report backs these flags. The questions below are stated
          from the design record; the membership and magnitude they refer to
          could not be read for this node.
        </p>
      ) : null}
      <ul className="mt-2 space-y-2">
        {QUESTIONS.map((q) => (
          <li
            key={q.ticker}
            data-testid={`alias-question-${q.ticker}`}
            className="rounded border border-zinc-800 bg-zinc-900/40 p-3"
          >
            <div className="flex flex-wrap items-baseline gap-2">
              <a
                href={`/stock/${q.ticker}`}
                className="font-mono text-sm text-zinc-200 hover:underline"
              >
                {q.ticker}
              </a>
              {exposures === null ? null : (
                <Reading found={exposures.find((e) => e.ticker === q.ticker)} />
              )}
            </div>
            <p className="mt-1 text-xs text-zinc-400">{q.question}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}
