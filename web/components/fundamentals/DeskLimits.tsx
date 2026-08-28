import type { DeskLimitsResponse } from "@/lib/api";

/**
 * What the desk cannot say — computed, not asserted.
 *
 * THE NET-INCOME BASIS SPLIT IS DESCRIPTIVE AND MUST NEVER READ AS PASS/FAIL.
 * The original premise — that income-statement net income disagreeing with the
 * cash-flow statement's is a data-integrity failure — was DISPROVED. The
 * income statement reports attributable-to-parent, post-discontinued-ops; the
 * cash-flow statement opens from consolidated net income INCLUDING
 * noncontrolling interests (ASC 230, indirect method). A disagreement is
 * usually correct accounting on both sides: measured on 342 of 419 tickers,
 * worked case VZ 2010-Q3 where 2,698M = 881M + 1,817M NCI. Argon stores no NCI
 * field and therefore CANNOT attribute the difference — so the honest render
 * is the count and the names, with the reason, and no verdict.
 *
 * The sign flip is the separate, genuine check on the same axis: a literal
 * inversion between the two statements, measured 5 of 28,973 rows. That one IS
 * a violation and is labelled as one. Keeping the two in different regions is
 * what stops the rare real defect from being diluted by the common correct
 * difference — and stops the common difference from inheriting the rare one's
 * alarm.
 */

export function DeskLimits({
  data,
  error,
}: {
  data: DeskLimitsResponse | null;
  error?: string;
}) {
  if (error != null) {
    return (
      <section data-testid="desk-limits" className="mt-6">
        <h2 className="text-sm font-semibold text-zinc-200">
          What this desk cannot say
        </h2>
        <p className="mt-2 text-xs text-red-300" role="alert">
          The limits request failed: {error}
        </p>
      </section>
    );
  }
  if (data === null) {
    return (
      <section data-testid="desk-limits" className="mt-6">
        <h2 className="text-sm font-semibold text-zinc-200">
          What this desk cannot say
        </h2>
        <p
          data-testid="desk-limits-absent"
          className="mt-2 text-xs text-zinc-500"
        >
          The limits panel was never computed for this section.
        </p>
      </section>
    );
  }
  return (
    <section data-testid="desk-limits" className="mt-6">
      <h2 className="text-sm font-semibold text-zinc-200">
        What this desk cannot say
      </h2>

      <div
        data-testid="ni-basis"
        className="mt-2 rounded border border-zinc-800 p-3"
      >
        <p className="text-xs text-zinc-300">
          Net income on the two statements:{" "}
          <span className="tabular-nums text-zinc-100">
            {data.ni_basis_agree}
          </span>{" "}
          comparable pairs match,{" "}
          <span className="tabular-nums text-zinc-100">
            {data.ni_basis_differ}
          </span>{" "}
          differ.
        </p>
        <p className="mt-1 text-[11px] text-zinc-500">
          A difference here is usually correct on both sides. The income
          statement reports income attributable to the parent; under ASC 230 the
          cash-flow statement opens from consolidated income including
          noncontrolling interests. Argon stores no NCI field, so it cannot
          attribute the gap — it can only show you that it is there.
        </p>
        {data.ni_largest_basis_differences.length > 0 ? (
          <p className="mt-1 font-mono text-[11px] text-zinc-400">
            widest: {data.ni_largest_basis_differences.join(", ")}
          </p>
        ) : null}
      </div>

      <div
        data-testid="ni-sign-flips"
        className="mt-2 rounded border border-amber-500/30 bg-amber-500/5 p-3"
      >
        <p className="text-xs text-zinc-300">
          <span className="tabular-nums text-amber-300">
            {data.ni_sign_flip_violations}
          </span>{" "}
          sign-flip violation
          {data.ni_sign_flip_violations === 1 ? "" : "s"} — the two statements
          disagree on the sign itself. This one is a genuine integrity
          violation, and unlike the basis difference above it has no accounting
          reading that makes it correct.
        </p>
      </div>

      <p
        data-testid="withheld-composite"
        className="mt-2 rounded border border-zinc-800 p-3 text-xs text-zinc-400"
      >
        {data.withheld_composite}
      </p>

      <div data-testid="membership-evidence" className="mt-2">
        <h3 className="text-[10px] uppercase tracking-wide text-zinc-600">
          membership evidence (memberships, not companies)
        </h3>
        <ul className="mt-1 flex flex-wrap gap-3">
          {data.membership_evidence.map((e) => (
            <li
              key={e.evidence_class}
              data-testid={`evidence-${e.evidence_class}`}
              className="text-[11px] text-zinc-400"
            >
              <span className="tabular-nums text-zinc-200">
                {e.memberships}
              </span>{" "}
              {e.evidence_class}
            </li>
          ))}
        </ul>
      </div>

      <div className="mt-2">
        <h3 className="text-[10px] uppercase tracking-wide text-zinc-600">
          exposure coverage
        </h3>
        <ul className="mt-1 space-y-1">
          {data.exposure_coverage.map((c) => (
            <li
              key={c.chain}
              data-testid={`exposure-${c.chain}`}
              className="text-[11px] text-zinc-400"
            >
              <span className="font-mono text-zinc-300">{c.chain}</span> ·{" "}
              <span className="tabular-nums text-zinc-200">{c.members}</span>{" "}
              members ·{" "}
              <span className="tabular-nums text-zinc-200">
                {c.with_exposure}
              </span>{" "}
              with an exposure row ·{" "}
              <span className="tabular-nums text-zinc-200">
                {c.with_magnitude}
              </span>{" "}
              with a disclosed magnitude
            </li>
          ))}
        </ul>
        {/* Three denominators, because they answer three different questions.
            Showing only the first invites the reader to assume the third. */}
      </div>
    </section>
  );
}
