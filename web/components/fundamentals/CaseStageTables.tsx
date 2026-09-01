/**
 * Stage detail — every member of every stage, named.
 *
 * A company with no TTM growth in the store is NAMED, flagged, and excluded
 * from the stage median. Never dropped, never imputed to zero: dropping it
 * would make the stage look smaller than it is, and zeroing it would make an
 * absence in Argon read as a collapse at a real business.
 *
 * EVERY ROW IS THAT COMPANY'S LATEST AVAILABLE RECORD, so two rows may sit on
 * different fiscal periods; this is not a synchronised quarter. The API
 * carries no per-row period, so none is printed rather than defaulted.
 *
 * Ticker cells link to the stock page, which is where a figure's filing date
 * and its raw line items live. The stage median prints its own coverage
 * beside it, so no median on this page ever stands alone.
 */

import Link from "next/link";

import type { CaseStage, CaseStageMember, DeskCase } from "@/lib/api";
import {
  DASH,
  GROWTH_CAP,
  MID,
  pct,
  sgn,
  caseToken,
  stageLabel,
  summariseCase,
  valuationPhrase,
} from "@/lib/fundamentals/desk";

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
  padding: "8px 12px",
  borderBottom: "1px solid var(--border-dim)",
  whiteSpace: "nowrap",
};

const td: React.CSSProperties = {
  padding: "7px 12px",
  borderBottom: "1px solid var(--border-dim)",
  fontSize: 12,
  color: "var(--text-secondary)",
  verticalAlign: "top",
};

const num: React.CSSProperties = {
  ...td,
  textAlign: "right",
  fontFamily: MONO,
  fontVariantNumeric: "tabular-nums",
  whiteSpace: "nowrap",
};

function Pill({
  tone,
  children,
}: {
  tone: "warn" | "bad" | "info";
  children: React.ReactNode;
}) {
  const color =
    tone === "warn"
      ? "var(--warning)"
      : tone === "bad"
        ? "var(--negative)"
        : "var(--text-muted)";
  return (
    <span
      style={{
        display: "inline-block",
        marginRight: 5,
        padding: "1px 6px",
        borderRadius: 4,
        border: `1px solid ${color}`,
        color,
        fontFamily: MONO,
        fontSize: 9.5,
        letterSpacing: 0.6,
        textTransform: "uppercase",
      }}
    >
      {children}
    </span>
  );
}

function flags(m: CaseStageMember) {
  const out: React.ReactNode[] = [];
  if (m.reported_currency)
    out.push(
      <Pill key="fx" tone="info">
        {m.reported_currency}
      </Pill>,
    );
  if (m.rev_yoy != null && m.rev_yoy > GROWTH_CAP)
    out.push(
      <Pill key="off" tone="warn">
        off scale
      </Pill>,
    );
  if (m.gross_margin != null && m.gross_margin < 0)
    out.push(
      <Pill key="gm" tone="bad">
        negative GM
      </Pill>,
    );
  return out;
}

function StageRows({ stage }: { stage: CaseStage }) {
  return (
    <>
      {stage.members.map((m, j) => (
        <tr key={`${stage.layer}-${m.ticker}`}>
          <td style={{ ...td, width: "24%" }}>
            {j === 0 ? (
              <>
                <strong style={{ color: "var(--text-primary)" }}>
                  {stageLabel(stage.layer)}
                </strong>
                <br />
                <span
                  style={{
                    fontFamily: MONO,
                    fontSize: 10.5,
                    color: "var(--text-muted)",
                  }}
                >
                  median {sgn(stage.median_rev_yoy)} {MID} growth available{" "}
                  {stage.reporting}/{stage.total}
                </span>
              </>
            ) : null}
          </td>
          <td style={{ ...td, fontFamily: MONO }}>
            <Link
              href={`/stock/${m.ticker}`}
              style={{ color: "var(--text-primary)" }}
            >
              {m.ticker}
            </Link>
          </td>
          <td style={num}>
            {m.rev_yoy == null ? (
              <span style={{ color: "var(--warning)" }}>
                TTM growth unavailable
              </span>
            ) : (
              sgn(m.rev_yoy)
            )}
          </td>
          <td style={num}>
            {m.gross_margin == null ? DASH : pct(m.gross_margin)}
          </td>
          <td style={num}>
            {valuationPhrase(m.spot_percentile)}
          </td>
          <td style={td}>{flags(m)}</td>
        </tr>
      ))}
    </>
  );
}

export function CaseStageTables({ cases }: { cases: DeskCase[] }) {
  const all = cases.flatMap((c) => c.stages.flatMap((s) => s.members));
  const seen = new Map<string, CaseStageMember>();
  for (const m of all) if (!seen.has(m.ticker)) seen.set(m.ticker, m);
  const members = [...seen.values()];
  const noBand = members.filter((m) => m.spot_percentile == null);
  const absent = members.filter((m) => m.rev_yoy == null);
  const offScale = members.filter(
    (m) => m.rev_yoy != null && m.rev_yoy > GROWTH_CAP,
  );

  return (
    <div data-testid="case-stage-tables">
      <Note>
        Each stage lists every member at its own latest available record, so
        two rows may sit on different fiscal periods. A company with no TTM
        growth in the store is flagged and excluded from the stage median{" "}
        {DASH} never dropped, never imputed to zero. Stage medians are the
        equal-weight median of the members carrying that metric.
      </Note>

      {cases.map((kase, i) => {
        const summary = summariseCase(kase.stages);
        if (!summary) return null;
        return (
          <div key={kase.slug} style={{ marginTop: 22 }}>
            <h3
              style={{
                fontFamily: MONO,
                fontSize: 12,
                fontWeight: 700,
                letterSpacing: 1.2,
                textTransform: "uppercase",
                color: `var(${caseToken(i)})`,
              }}
            >
              {kase.label}
            </h3>
            <div style={{ ...panelStyle, marginTop: 8, overflowX: "auto" }}>
              <table
                style={{
                  width: "100%",
                  borderCollapse: "collapse",
                  minWidth: 700,
                }}
              >
                <thead>
                  <tr>
                    <th style={th}>Stage</th>
                    <th style={th}>Company</th>
                    <th style={{ ...th, textAlign: "right" }}>
                      Revenue growth (TTM YoY, %)
                    </th>
                    <th style={{ ...th, textAlign: "right" }}>
                      Reported gross margin (latest quarter, %)
                    </th>
                    <th style={{ ...th, textAlign: "right" }}>
                      Valuation vs own history
                    </th>
                    <th style={th}>Flags</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.downstreamFirst.map((stage) => (
                    <StageRows key={stage.layer} stage={stage} />
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        );
      })}

      <Finding tone="bad" label="What this screen cannot tell you">
        <Num>{noBand.length}</Num> of the <Num>{members.length}</Num> companies
        across the cases carry no valuation band, so the funnels say where
        growth is and stay deliberately silent on what it costs.{" "}
        <Num>{absent.length}</Num> have no TTM growth available
        {absent.length ? ` (${absent.map((m) => m.ticker).join(", ")})` : ""}:
        they sit in their stage as hollow marks, excluded from the median but
        never removed from the chain.{" "}
        {offScale.length ? (
          <>
            {offScale.map((m, i) => (
              <span key={m.ticker}>
                {i > 0 ? " and " : ""}
                <strong style={{ color: "var(--text-secondary)" }}>
                  {m.ticker}
                </strong>{" "}
                at <Num>{sgn(m.rev_yoy, 0)}</Num>
              </span>
            ))}{" "}
            {offScale.length > 1 ? "sit" : "sits"} past the end of the radius
            scale {DASH} flagged above, clamped to the rim, and not permitted to
            set the scale for everyone else.{" "}
          </>
        ) : null}
        And because the funnels share one scale, a change to any case&apos;s
        axis would silently rewrite the other&apos;s shape {DASH} which is the
        one thing an implementation here must not get wrong.
      </Finding>
    </div>
  );
}
