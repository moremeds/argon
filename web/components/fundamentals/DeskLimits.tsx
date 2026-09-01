/**
 * Question 5 — what are the data limits?
 *
 * Every row here is
 * MEASURED rather than asserted: the numbers come from `/limits`, and the web
 * layer writes captions OVER them, never instead of them.
 *
 * The one exception is `withheld_composite`, which is legitimately prose —
 * the reason a number is withheld is not itself a number — and is published
 * verbatim under the table rather than paraphrased.
 */

import type { DeskLimitsResponse } from "@/lib/api";

import { DASH, MID } from "@/lib/fundamentals/desk";

import {
  Finding,
  MONO,
  Note,
  Num,
  labelStyle,
  panelStyle,
} from "./DeskSection";

const th: React.CSSProperties = {
  ...labelStyle,
  textAlign: "left",
  padding: "9px 12px",
  borderBottom: "1px solid var(--border-dim)",
  whiteSpace: "nowrap",
};

const td: React.CSSProperties = {
  padding: "11px 12px",
  borderBottom: "1px solid var(--border-dim)",
  fontSize: 12,
  lineHeight: 1.55,
  color: "var(--text-secondary)",
  verticalAlign: "top",
};

export function DeskLimits({ data }: { data: DeskLimitsResponse }) {
  const fx = data.non_usd_filers;
  const exposure = data.exposure_coverage.reduce(
    (a, e) => ({
      members: a.members + e.members,
      magnitude: a.magnitude + e.with_magnitude,
    }),
    { members: 0, magnitude: 0 },
  );

  const rows: [string, React.ReactNode, string][] = [
    [
      "Statements are not all in one currency",
      <>
        <Num>{fx.length}</Num> companies on this desk file in another currency:{" "}
        {fx.map((f, i) => (
          <span key={f.ticker}>
            {i > 0 ? ", " : ""}
            {f.ticker} ({f.currencies.join("/")})
          </span>
        ))}
      </>,
      "No dollar figure is summed across companies anywhere on this desk. Every cross-name number is a ratio or a count — capex on question one is the single exception, and it is restricted to USD filers with the excluded name printed underneath.",
    ],
    [
      "Chain membership rests on inference, not disclosure",
      <>
        <Num>{exposure.magnitude}</Num> of <Num>{exposure.members}</Num>{" "}
        memberships carry a magnitude a company disclosed {MID}{" "}
        {data.membership_evidence.map((e, i) => (
          <span key={e.evidence_class}>
            {i > 0 ? ", " : ""}
            <Num>{e.memberships}</Num> {e.evidence_class}
          </span>
        ))}
      </>,
      "No arrows on the chain map. Flow is drawn only where the taxonomy defines ranked stages, which today is the case chains and nothing else.",
    ],
    [
      "Companies drop out of the medians",
      <>Stage and chain medians are taken over reporting members only</>,
      `Coverage prints beside every median, and a non-reporting company is named inside its stage ${DASH} never dropped, never imputed to zero.`,
    ],
    [
      "A percentile is not a forecast",
      <>
        Within-ticker <span style={{ fontFamily: MONO }}>sales_to_ev</span> IC
        +0.0744 (t 5.77); cross-sectional{" "}
        <span style={{ fontFamily: MONO }}>book_to_price</span> IC −0.0365 (t
        −2.32)
        <br />
        {/* These four figures are the ONE class of number on this desk that
            does not move with the data, and they must not be mistaken for
            live readings. They come from a completed study; the citation
            below is what makes them a citation rather than a measurement the
            page is claiming to have just taken. */}
        <span style={{ color: "var(--text-muted)", fontSize: 11 }}>
          frozen from{" "}
          <span style={{ fontFamily: MONO }}>
            2026-08-12-fundamental-valuation-anchors
          </span>{" "}
          {DASH} a completed study, not a live reading
        </span>
      </>,
      "The valuation strip cannot be sorted, and no section of this desk produces a score, a rank or an allocation.",
    ],
  ];

  return (
    <div data-testid="desk-limits">
      <div style={{ ...panelStyle, marginTop: 16, overflowX: "auto" }}>
        <table
          style={{
            width: "100%",
            borderCollapse: "collapse",
            minWidth: 620,
          }}
        >
          <thead>
            <tr>
              <th style={th}>What could be wrong</th>
              <th style={th}>Measured extent</th>
              <th style={th}>How the desk handles it</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([what, extent, handling]) => (
              <tr key={what}>
                <td
                  style={{ ...td, color: "var(--text-primary)", width: "22%" }}
                >
                  <strong>{what}</strong>
                </td>
                <td style={{ ...td, width: "40%" }}>{extent}</td>
                <td style={td}>{handling}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Finding tone="bad" label="Rule this measurement forced">
        Summing gross profit across a chain looked reasonable until it was
        tried: on 2026-08-26 it put the Foundry chain at roughly{" "}
        <Num>$930B</Num> of quarterly gross profit, because TSM and UMC file in
        TWD and the store holds the filed figure.{" "}
        <strong style={{ color: "var(--text-secondary)" }}>
          So this desk does not add currency amounts across companies at all.
        </strong>{" "}
        Growth rates, margins and percentiles are unaffected {DASH} a ratio
        carries no currency.
      </Finding>

      <div style={{ ...panelStyle, marginTop: 16, overflowX: "auto" }}>
        <div
          style={{
            ...labelStyle,
            padding: "9px 12px",
            borderBottom: "1px solid var(--border-dim)",
          }}
        >
          Exposure coverage, per chain
        </div>
        <table
          style={{ width: "100%", borderCollapse: "collapse", minWidth: 520 }}
          data-testid="membership-evidence"
        >
          <thead>
            <tr>
              <th style={th}>Chain</th>
              <th style={{ ...th, textAlign: "right" }}>Members</th>
              <th style={{ ...th, textAlign: "right" }}>
                With an exposure row
              </th>
              <th style={{ ...th, textAlign: "right" }}>
                With a disclosed magnitude
              </th>
            </tr>
          </thead>
          <tbody>
            {/* All THREE denominators, always. They answer three different
                questions, and a surface showing only the first invites the
                reader to assume the third. */}
            {data.exposure_coverage.map((e) => (
              <tr key={e.chain} data-testid={`exposure-${e.chain}`}>
                <td style={{ ...td, fontFamily: MONO }}>{e.chain}</td>
                <td style={{ ...td, textAlign: "right", fontFamily: MONO }}>
                  {e.members}
                </td>
                <td style={{ ...td, textAlign: "right", fontFamily: MONO }}>
                  {e.with_exposure}
                </td>
                <td style={{ ...td, textAlign: "right", fontFamily: MONO }}>
                  {e.with_magnitude}
                </td>
              </tr>
            ))}
            {data.membership_evidence.map((e) => (
              <tr
                key={e.evidence_class}
                data-testid={`evidence-${e.evidence_class}`}
              >
                <td style={{ ...td, fontFamily: MONO }} colSpan={3}>
                  memberships resting on {e.evidence_class} evidence
                </td>
                <td style={{ ...td, textAlign: "right", fontFamily: MONO }}>
                  {e.memberships}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div data-testid="withheld-composite">
        <Note>{data.withheld_composite}</Note>
      </div>

      <div data-testid="ni-basis">
        <Note>
          {/* Wording is load-bearing: this block is DESCRIPTIVE and a test
              asserts it never reads as pass/fail. A disagreement here is
              usually correct accounting on both sides. */}
          Also measured, and descriptive rather than diagnostic:{" "}
          <Num>{data.ni_basis_agree}</Num> comparable net-income pairs match
          across the two statements and <Num>{data.ni_basis_differ}</Num>{" "}
          differ. A disagreement is usually correct accounting on both sides{" "}
          {DASH} income-statement net income is attributable-to-parent, while
          the cash-flow statement opens from consolidated net income including
          noncontrolling interests (ASC 230 indirect). Argon stores no NCI field
          and cannot attribute the difference, so it is never rendered as an
          integrity problem. The widest gaps sit at{" "}
          {data.ni_largest_basis_differences.join(", ")}.
        </Note>
      </div>

      <div data-testid="ni-sign-flips">
        <Note>
          The genuine check on this axis is separate and rare:{" "}
          <Num>{data.ni_sign_flip_violations}</Num> literal sign inversions
          between the two statements. That one IS a violation, and it is kept
          apart from the basis split for exactly that reason.
        </Note>
      </div>
    </div>
  );
}
