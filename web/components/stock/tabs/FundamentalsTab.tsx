"use client";
import { useEffect, useState } from "react";
import type { components } from "@/lib/types";
import { api } from "@/lib/api";
import { fmtDecimal, fmtPct } from "@/lib/formatters";
import { FundamentalSparkline } from "../panels/FundamentalSparkline";

type Card = components["schemas"]["FundamentalCardResponse"];
type Subscore = components["schemas"]["FundamentalSubscore"];
type Pct = components["schemas"]["FundamentalPercentile"];

const LABELS: Record<string, string> = {
  rev_growth: "Revenue growth",
  gross_margin: "Gross margin",
  op_margin: "Operating margin",
  fcf_margin: "FCF margin",
  roe: "Return on equity",
  neg_net_debt_ebitda: "Net cash / EBITDA",
  asset_turnover: "Asset turnover",
};

const panelStyle: React.CSSProperties = {
  background: "var(--bg-panel)",
  border: "1px solid var(--border-dim)",
  borderRadius: 4,
  padding: 16,
  fontFamily: "var(--font-mono)",
  minWidth: 0,
};

const labelStyle: React.CSSProperties = {
  fontSize: 10,
  letterSpacing: 1.5,
  textTransform: "uppercase",
  color: "var(--text-muted)",
};

/** 0.913 -> "91st". Rounded to a whole percentile: the third decimal of a rank
 *  among 253 names is noise, and printing it would imply precision we lack. */
function ordinal(p: number): string {
  const n = Math.round(p * 100);
  const rem100 = n % 100;
  if (rem100 >= 11 && rem100 <= 13) return `${n}th`;
  return `${n}${["th", "st", "nd", "rd"][n % 10] ?? "th"}`;
}

function PercentileTag({ pct }: { pct: Pct | null | undefined }) {
  if (!pct) return null;
  return (
    // No colour ramp. A percentile locates the name in its panel; it is not a
    // quality score and not an expected return (zero gross alpha measured
    // 2026-08-12), so painting it green would assert something untrue.
    <span style={{ ...labelStyle, fontSize: 9, letterSpacing: 0.5 }}>
      {ordinal(pct.percentile)} of {pct.n}
    </span>
  );
}

function formatValue(s: Subscore): string {
  if (s.value == null) return "na";
  return s.unit === "ratio" ? fmtPct(s.value, 1) : `${fmtDecimal(s.value, 2)}x`;
}

function SubscoreTile({ s, dates }: { s: Subscore; dates: string[] }) {
  const suppressed = s.suppressed_by.length > 0;
  const series = s.series ?? [];
  return (
    <div
      style={{ ...panelStyle, padding: 12 }}
      data-testid={`subscore-${s.feature}`}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          gap: 8,
        }}
      >
        <span style={labelStyle}>{LABELS[s.feature] ?? s.feature}</span>
        <PercentileTag pct={s.percentile} />
      </div>
      <div
        style={{
          fontSize: 22,
          fontWeight: 700,
          color: s.value == null ? "var(--text-muted)" : "var(--text-primary)",
          margin: "6px 0",
        }}
      >
        {formatValue(s)}
      </div>
      {series.length ? (
        <FundamentalSparkline
          values={series}
          dates={dates}
          label={LABELS[s.feature] ?? s.feature}
          stroke="var(--text-secondary)"
        />
      ) : null}
      {suppressed ? (
        <div
          style={{
            fontSize: 10,
            color: "var(--warning)",
            lineHeight: 1.4,
            marginTop: 6,
          }}
        >
          suppressed · {s.suppressed_by.join(", ")}
        </div>
      ) : (
        <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 6 }}>
          {s.direction === "higher_better"
            ? "higher better"
            : "no direction claimed"}
        </div>
      )}
    </div>
  );
}

export function FundamentalsTab({ ticker }: { ticker: string }) {
  const [card, setCard] = useState<Card | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const c = await api.fundamentals(ticker);
        if (live) setCard(c);
      } catch (e) {
        // A 404 here is the normal case for any name outside the tier-1
        // universe, so it renders as an empty state rather than an error.
        if (live) setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      live = false;
    };
  }, [ticker]);

  if (error) {
    return (
      <div style={panelStyle}>
        <div style={labelStyle}>FUNDAMENTALS · {ticker}</div>
        <div
          style={{ color: "var(--text-muted)", fontSize: 12, marginTop: 10 }}
          data-testid="fundamentals-empty"
        >
          No fundamental score for {ticker}. Only the tier-1 universe is
          ingested and scored.
        </div>
      </div>
    );
  }
  if (!card) {
    return (
      <div style={{ ...panelStyle, color: "var(--text-muted)", fontSize: 12 }}>
        Loading…
      </div>
    );
  }

  const { coverage: cov, provenance: prov } = card;
  const dates = card.series_dates ?? [];
  const compSeries = card.composite_series ?? [];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <div style={panelStyle} data-testid="fundamentals-composite">
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <span style={labelStyle}>COMPOSITE · {card.ticker}</span>
          <span style={{ ...labelStyle, fontSize: 9, letterSpacing: 0.5 }}>
            {/* knowledge_date, never the as_of bucket: as_of is a cross-section
                slot and can sit ahead of the filing it describes. */}
            KNOWN {prov.knowledge_date}
            {prov.filing_date_known ? "" : " (EST)"}
          </span>
        </div>
        <div
          style={{
            display: "flex",
            alignItems: "baseline",
            gap: 12,
            margin: "8px 0 6px",
          }}
        >
          <span
            style={{
              fontSize: 32,
              fontWeight: 700,
              color: "var(--text-primary)",
            }}
          >
            {card.composite == null ? "na" : fmtDecimal(card.composite, 2)}
          </span>
          <PercentileTag pct={card.composite_percentile} />
        </div>
        {compSeries.length ? (
          <div style={{ margin: "10px 0" }}>
            {/* The date axis lives in the sparkline itself, so the composite
                and the seven tiles cannot drift apart. */}
            <FundamentalSparkline
              values={compSeries}
              dates={dates}
              label="Composite"
              height={72}
            />
          </div>
        ) : null}
        <div
          style={{ fontSize: 11, color: "var(--text-muted)", lineHeight: 1.5 }}
        >
          Cross-sectional z-mean of the seven measured features, against a panel
          of {card.panel_size} names. A sort key across the wide tier only —{" "}
          <strong>not</strong>{" "}
          an expected return. Fundamental change does not
          precede this name&rsquo;s own drawdown (measured 2026-08-12); read
          every trajectory here as description, never as a price call.
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
          gap: 12,
        }}
      >
        {card.subscores.map((s) => (
          <SubscoreTile key={s.feature} s={s} dates={dates} />
        ))}
      </div>

      <div style={panelStyle} data-testid="fundamentals-coverage">
        <div style={labelStyle}>COVERAGE</div>
        <div
          style={{
            fontSize: 12,
            color: "var(--text-secondary)",
            marginTop: 8,
            lineHeight: 1.7,
          }}
        >
          <div>
            {cov.features_present} of {cov.features_total} features scored.
          </div>
          <div
            style={{
              color: cov.missing.length
                ? "var(--text-secondary)"
                : "var(--text-muted)",
            }}
          >
            Not reported:{" "}
            {cov.missing.length
              ? cov.missing.map((f) => LABELS[f] ?? f).join(", ")
              : "none"}
          </div>
          <div
            style={{
              color: cov.suppressed.length
                ? "var(--warning)"
                : "var(--text-muted)",
            }}
          >
            Reported but not believed:{" "}
            {cov.suppressed.length
              ? cov.suppressed.map((f) => LABELS[f] ?? f).join(", ")
              : "none"}
          </div>
          {cov.suppressed.length ? (
            <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
              Dashed marks on a trajectory are quarters excluded for the same
              reason.
            </div>
          ) : null}
        </div>
      </div>

      <div style={panelStyle} data-testid="fundamentals-provenance">
        <div style={labelStyle}>PROVENANCE</div>
        <div
          style={{
            fontSize: 11,
            color: "var(--text-muted)",
            marginTop: 8,
            lineHeight: 1.8,
            wordBreak: "break-all",
          }}
        >
          <div>
            period {prov.period_end} · cross-section {prov.as_of} ·{" "}
            {prov.source_obs_count} source rows · {dates.length} quarters
            plotted
          </div>
          <div>
            filing date{" "}
            {prov.filing_date_known
              ? "known"
              : "unknown — knowledge date is period end + 45d"}
          </div>
          <div>engine {prov.engine_version}</div>
          <div>inputs {prov.inputs_hash.slice(0, 16)}…</div>
        </div>
      </div>
    </div>
  );
}
