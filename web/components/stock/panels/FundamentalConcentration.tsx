import type { components } from "@/lib/types";
import { FundamentalSparkline } from "./FundamentalSparkline";
import { labelStyle, panelStyle } from "./fundamentalShared";

type Concentration = components["schemas"]["FundamentalConcentrationResponse"];
type Family = components["schemas"]["FundamentalConcentrationFamily"];

const FAMILIES = [
  ["segment", "by reportable segment"],
  ["geography", "by geography"],
] as const;

const pct = (v: number) => `${(v * 100).toFixed(1)}%`;

/**
 * Where one name's revenue is concentrated, by segment and by geography.
 *
 * **This block is descriptive and nothing on it is a signal.** Measured over
 * 401 tickers, the top share moves a median 1.20pp per quarter against
 * annual/quarterly basis contamination of median 2.5pp and p90 17.5pp. The
 * level survives that noise and is near-static — a public, filing-lagged,
 * highly persistent characteristic is a factor loading, not alpha. So there is
 * no rank here, no percentile against other names, no score, and no
 * contribution to the composite. The copy says so on screen rather than only in
 * this comment, because a number rendered beside seven scored tiles will be
 * read as an eighth unless it is told not to be.
 *
 * Three rendering constraints, each one a mistake this lane has already paid
 * for:
 *
 * - **The member string is raw.** Filers mix `country:US` with custom members
 *   like `nvda:ChinaIncludingHongKongMember` and with continent aggregates.
 *   Mapping those to flags or country names means inventing a taxonomy the
 *   filer did not use; the share is defensible, a beautified label is not.
 * - **Absent renders `na`, never 0.** A 0% top share reads as "no
 *   concentration risk", which is a claim about the company. Absence is a claim
 *   about our coverage, and the two must not look alike.
 * - **Dropped annual periods are listed, not hidden.** They are excluded from
 *   the trend because an annual total mixed into a quarterly series moves the
 *   share by several times the signal's own quarterly step — but a reader
 *   reconciling against the filings needs to see the period existed.
 */
export function FundamentalConcentration({ c }: { c: Concentration }) {
  const dates = c.trend.map((p) => p.report_date);
  const series: Record<string, (number | null)[]> = {
    segment: c.trend.map((p) => p.segment_top_share ?? null),
    geography: c.trend.map((p) => p.geography_top_share ?? null),
  };

  return (
    <section style={{ ...panelStyle, gridColumn: "1 / -1" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          gap: 12,
        }}
      >
        <span style={labelStyle}>Revenue concentration</span>
        <span style={{ ...labelStyle, color: "var(--text-dim)" }}>
          descriptive · not scored
        </span>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
          gap: 16,
          marginTop: 12,
        }}
      >
        {FAMILIES.map(([key, title]) => {
          const family = c[key] as Family | null;
          return (
            <div key={key} style={{ minWidth: 0 }}>
              <div style={labelStyle}>{title}</div>
              {family == null ? (
                <div
                  style={{
                    fontSize: 22,
                    color: "var(--text-muted)",
                    marginTop: 4,
                  }}
                >
                  na
                </div>
              ) : (
                <>
                  <div style={{ fontSize: 22, marginTop: 4 }}>
                    {pct(family.top_share)}
                  </div>
                  <div
                    style={{
                      fontSize: 11,
                      color: "var(--text-dim)",
                      wordBreak: "break-all",
                    }}
                  >
                    {family.top_member}
                  </div>
                  <div
                    style={{
                      fontSize: 10,
                      color: "var(--text-muted)",
                      marginTop: 2,
                    }}
                  >
                    top of {family.n_members} · {family.report_date}
                    {family.level !== "all" ? ` · ${family.level}` : ""}
                  </div>
                </>
              )}
              <div style={{ marginTop: 8 }}>
                <FundamentalSparkline
                  values={series[key]}
                  dates={dates}
                  label={title}
                />
              </div>
            </div>
          );
        })}
      </div>

      {c.dropped_annual_periods.length > 0 && (
        <div
          style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 12 }}
        >
          {c.dropped_annual_periods.length} annual period
          {c.dropped_annual_periods.length === 1 ? "" : "s"} excluded from the
          trend: {c.dropped_annual_periods.join(", ")}
        </div>
      )}
      <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 4 }}>
        Top member&apos;s share of consolidated revenue, from the filer&apos;s
        own XBRL disaggregation. Member names are as filed.{" "}
        {c.derivation_version}
      </div>
    </section>
  );
}
