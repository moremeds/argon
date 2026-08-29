/**
 * The two cases, summarised — and why there are two rather than one.
 *
 * They were not picked for being interesting. They were picked because they
 * are the only chains in this section whose stages carry an explicit order,
 * and as it turns out they answer the same question in opposite directions.
 * ONE CASE WOULD HAVE BEEN MISTAKEN FOR A RULE.
 */

import type { DeskCase } from "@/lib/api";

import {
  DASH,
  belowCustomer,
  MID,
  TIMES,
  pct,
  sgn,
  caseToken,
  stageLabel,
  summariseCase,
  type CaseSummary,
} from "@/lib/fundamentals/desk";

import { Finding, MONO, Num, labelStyle, panelStyle } from "./DeskSection";

function Row({ term, value }: { term: string; value: string }) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        gap: 12,
        padding: "5px 0",
        borderTop: "1px solid var(--border-dim)",
      }}
    >
      <dt style={{ ...labelStyle, letterSpacing: 1.1 }}>{term}</dt>
      <dd
        style={{
          fontFamily: MONO,
          fontSize: 11.5,
          color: "var(--text-secondary)",
          textAlign: "right",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {value}
      </dd>
    </div>
  );
}

function marginSpan(summary: CaseSummary): string {
  const gms = summary.downstreamFirst
    .map((s) => s.median_gross_margin)
    .filter((v): v is number => v != null);
  if (gms.length === 0) return "na";
  return `${pct(Math.min(...gms), 0)} ${DASH} ${pct(Math.max(...gms), 0)}`;
}

export function CaseCards({ cases }: { cases: DeskCase[] }) {
  const summaries = cases.map((c) => ({
    kase: c,
    summary: summariseCase(c.stages),
  }));
  const usable = summaries.filter(
    (x): x is { kase: DeskCase; summary: CaseSummary } => x.summary !== null,
  );
  if (usable.length === 0) return null;

  const ranked = usable
    .filter((x) => x.summary.amplification != null)
    .sort(
      (a, b) =>
        (b.summary.amplification as number) -
        (a.summary.amplification as number),
    );

  return (
    <div data-testid="case-cards">
      <div
        style={{
          marginTop: 16,
          display: "grid",
          gap: 12,
          gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
        }}
      >
        {usable.map(({ kase, summary }, i) => {
          const accent = `var(${caseToken(i)})`;
          const fastest = [...summary.downstreamFirst]
            .filter((s) => s.median_rev_yoy != null)
            .sort(
              (a, b) =>
                (b.median_rev_yoy as number) - (a.median_rev_yoy as number),
            )[0];
          return (
            <div
              key={kase.slug}
              style={{
                ...panelStyle,
                borderTop: `2px solid ${accent}`,
                padding: "14px 16px 12px",
              }}
            >
              <h3
                style={{
                  fontFamily: MONO,
                  fontSize: 13,
                  fontWeight: 700,
                  letterSpacing: 0.8,
                  textTransform: "uppercase",
                  color: "var(--text-primary)",
                }}
              >
                {kase.label}
              </h3>
              <div
                style={{
                  marginTop: 10,
                  fontFamily: MONO,
                  fontSize: 30,
                  fontWeight: 700,
                  letterSpacing: 1,
                  color: accent,
                  fontVariantNumeric: "tabular-nums",
                }}
              >
                {summary.amplification == null
                  ? "na"
                  : `${summary.amplification.toFixed(2)}${TIMES}`}
              </div>
              <div style={{ ...labelStyle, marginTop: 2 }}>
                upstream growth divided by customer growth
              </div>
              <dl style={{ marginTop: 12 }}>
                <Row
                  term="stages"
                  value={String(summary.downstreamFirst.length)}
                />
                <Row
                  term="companies"
                  value={
                    summary.dualListed
                      ? `${summary.distinctCompanies} (${summary.dualListed} at two stages)`
                      : String(summary.distinctCompanies)
                  }
                />
                <Row
                  term="customer stage"
                  value={`${stageLabel(summary.customer.layer)}  ${sgn(summary.customer.median_rev_yoy)}`}
                />
                {fastest ? (
                  <Row term="fastest stage" value={stageLabel(fastest.layer)} />
                ) : null}
                <Row term="margin span" value={marginSpan(summary)} />
              </dl>
            </div>
          );
        })}
      </div>

      {ranked.length >= 2 ? (
        <WhyTwo strong={ranked[0]} weak={ranked[ranked.length - 1]} />
      ) : null}
    </div>
  );
}

function WhyTwo({
  strong,
  weak,
}: {
  strong: { kase: DeskCase; summary: CaseSummary };
  weak: { kase: DeskCase; summary: CaseSummary };
}) {
  const cm = weak.summary.customer.median_rev_yoy;
  const supplying = weak.summary.downstreamFirst.slice(1);
  const below = belowCustomer(weak.summary);
  // The slowest stage that is ACTUALLY below its customer, not merely the
  // slowest. The sentence below calls it "slower than the customers it
  // supplies", and if every supplying stage outgrew the customer that word
  // would be false while the number beside it stayed correct — the failure
  // mode this desk is least able to survive.
  const slowest = [...below]
    .filter((s) => s.median_rev_yoy != null)
    .sort(
      (a, b) => (a.median_rev_yoy as number) - (b.median_rev_yoy as number),
    )[0];

  // How far apart the two transmissions actually are. The adjective is drawn
  // from it rather than asserted: two cases that converged would still print
  // their true amplifications under a sentence claiming they diverge.
  const gap =
    (strong.summary.amplification as number) /
    (weak.summary.amplification as number);

  return (
    <Finding label="Why one case would not have been enough">
      One case would have been mistaken for a rule. Both chains are fed by the
      same capital expenditure and they transmit it{" "}
      {gap >= 1.5 ? "completely differently" : "at measurably different rates"}:{" "}
      {strong.kase.label.toLowerCase()}{" "}
      <Num>
        {(strong.summary.amplification as number).toFixed(2)}
        {TIMES}
      </Num>{" "}
      against {weak.kase.label.toLowerCase()}&apos;s{" "}
      <Num>
        {(weak.summary.amplification as number).toFixed(2)}
        {TIMES}
      </Num>
      .{" "}
      {slowest ? (
        <>
          Worse for the naive version of the thesis,{" "}
          <strong style={{ color: "var(--text-secondary)" }}>
            {stageLabel(slowest.layer)}
          </strong>{" "}
          grows at <Num>{sgn(slowest.median_rev_yoy)}</Num> {DASH}{" "}
          <em>slower</em> than the customers it supplies at <Num>{sgn(cm)}</Num>{" "}
          {DASH} and it is not alone: <Num>{below.length}</Num> of the{" "}
          {supplying.length} supplying stages sit below their own customer.{" "}
        </>
      ) : null}
      Proximity to the AI dollar does not guarantee participation in it, and no
      screen sorted on sector or growth would have surfaced that. The two cases
      are drawn on one shared scale for exactly this reason {MID} see the
      funnels below.
    </Finding>
  );
}
