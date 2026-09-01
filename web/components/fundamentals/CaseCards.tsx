/**
 * The case groups, summarised.
 *
 * They were not picked for being interesting. They are the chains in this
 * section whose stages carry an explicit order in the taxonomy.
 *
 * EACH GROUP'S MEDIAN STANDS ON ITS OWN. The card once headlined the upstream
 * median divided by the customer median and called it amplification; nothing
 * in this store traces a payment from one group to the other, so the ratio was
 * a transmission claim the data does not support. The two medians are printed
 * side by side instead, and the reader does the comparing.
 */

import type { DeskCase } from "@/lib/api";

import {
  DASH,
  pct,
  sgn,
  caseToken,
  stageLabel,
  summariseCase,
  type CaseSummary,
} from "@/lib/fundamentals/desk";

import { MONO, Note, labelStyle, panelStyle } from "./DeskSection";

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

function Figure({
  accent,
  label,
  value,
  sub,
}: {
  accent: string;
  label: string;
  value: string;
  sub: string;
}) {
  return (
    <div style={{ minWidth: 0 }}>
      <div style={{ ...labelStyle, letterSpacing: 1 }}>{label}</div>
      <div
        style={{
          marginTop: 4,
          fontFamily: MONO,
          fontSize: 22,
          fontWeight: 700,
          letterSpacing: 0.8,
          color: accent,
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {value}
      </div>
      <div
        style={{
          marginTop: 2,
          fontFamily: MONO,
          fontSize: 10.5,
          color: "var(--text-muted)",
        }}
      >
        {sub}
      </div>
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
                  marginTop: 12,
                  display: "grid",
                  gap: 10,
                  gridTemplateColumns: "1fr 1fr",
                }}
              >
                <Figure
                  accent={accent}
                  label="Customer-group revenue growth (TTM YoY, %)"
                  value={sgn(summary.customer.median_rev_yoy)}
                  sub={stageLabel(summary.customer.layer)}
                />
                <Figure
                  accent={accent}
                  label="Upstream-group revenue growth (TTM YoY, %)"
                  value={sgn(summary.upstream.median_rev_yoy)}
                  sub={stageLabel(summary.upstream.layer)}
                />
              </div>
              <div style={{ ...labelStyle, marginTop: 6 }}>
                equal-weight median of the group members carrying a TTM growth
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
                      ? `${summary.distinctCompanies} (${summary.dualListed} in two groups)`
                      : String(summary.distinctCompanies)
                  }
                />
                {fastest ? (
                  <Row term="fastest group" value={stageLabel(fastest.layer)} />
                ) : null}
                <Row
                  term="reported gross margin (latest quarter, %)"
                  value={marginSpan(summary)}
                />
              </dl>
            </div>
          );
        })}
      </div>

      <Note>
        The same company can sit in more than one group, and it is counted in
        each group it belongs to. Every figure is company-level: it is the
        whole company&apos;s reported revenue and margin, not the part of it
        that serves this chain. And these groups are not the buyer sample the
        capex panel sums {DASH} the two are built from different memberships,
        so a figure here does not describe the spenders there.
      </Note>
    </div>
  );
}
