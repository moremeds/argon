"use client";
import { useEffect, useState } from "react";
import type { components } from "@/lib/types";
import { api } from "@/lib/api";
import { fmtDecimal, fmtPct } from "@/lib/formatters";
import { FundamentalAnchorBand } from "../panels/FundamentalAnchorBand";
import { FundamentalCardBack } from "../panels/FundamentalCardBack";
import { FundamentalSparkline } from "../panels/FundamentalSparkline";

type Card = components["schemas"]["FundamentalCardResponse"];
type Statements = components["schemas"]["FundamentalStatementsResponse"];
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

/** The back before its data arrives — or after the fetch failed.
 *
 * These are different states and must read differently. A failed fetch left
 * showing "Loading…" claims progress that will never arrive, and the reader
 * waits instead of reloading. */
function BackPlaceholder({
  failed,
  onClose,
}: {
  failed: boolean;
  onClose: () => void;
}) {
  return (
    <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
      {failed ? (
        <>
          <strong style={{ color: "var(--warning)" }}>
            Components unavailable.
          </strong>{" "}
          The statement history did not load. The ratio on the front of the card
          is unaffected.
        </>
      ) : (
        "Loading components…"
      )}
      <button
        type="button"
        onClick={onClose}
        aria-label="Close details"
        style={{
          background: "none",
          border: "1px solid var(--border-dim)",
          borderRadius: 3,
          color: "var(--text-muted)",
          cursor: "pointer",
          fontSize: 10,
          marginLeft: 8,
          padding: "2px 8px",
        }}
      >
        close
      </button>
    </div>
  );
}

function SubscoreTile({
  s,
  dates,
  onOpen,
}: {
  s: Subscore;
  dates: string[];
  onOpen: () => void;
}) {
  const suppressed = s.suppressed_by.length > 0;
  const series = s.series ?? [];
  return (
    // A native button, not a div with handlers: Enter, Space, focus order and
    // the right role all come for free, and reimplementing them is how they get
    // missed. `font`/`color`/`textAlign` undo the UA button defaults so the tile
    // still looks like its neighbours.
    <button
      type="button"
      onClick={onOpen}
      style={{
        ...panelStyle,
        padding: 12,
        textAlign: "left",
        cursor: "pointer",
        font: "inherit",
        color: "inherit",
        width: "100%",
      }}
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
    </button>
  );
}

export function FundamentalsTab({ ticker }: { ticker: string }) {
  const [card, setCard] = useState<Card | null>(null);
  const [error, setError] = useState<string | null>(null);
  // All three carry the ticker they belong to, and the render derives from
  // that rather than from a reset in an effect. Two reasons, both load-bearing:
  // effects run AFTER render, so a reset leaves one frame showing the previous
  // ticker's components under the new ticker's header — a wrong chart that
  // looks right; and resetting state inside an effect is what
  // `react-hooks/set-state-in-effect` flags. Deriving makes the stale frame
  // unrepresentable instead of merely brief.
  const [openFeature, setOpenFeature] = useState<{
    ticker: string;
    feature: string;
  } | null>(null);
  const [statements, setStatements] = useState<Statements | null>(null);
  const [failedTicker, setFailedTicker] = useState<string | null>(null);

  const stmts = statements?.ticker === ticker ? statements : null;
  const open = openFeature?.ticker === ticker ? openFeature.feature : null;
  const statementsFailed = failedTicker === ticker;

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

  // Fetched on mount, not deferred to the first flip: the eighth card's
  // headline comes from this payload, so deferring would leave that card
  // showing an em dash until the reader happened to open some OTHER card.
  useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const s = await api.fundamentalStatements(ticker);
        if (live) setStatements(s);
      } catch {
        // A missing back is not a broken card: the front still states every
        // ratio. But it must render as UNAVAILABLE, not as loading — leaving
        // `statements` null with no failure flag spins "Loading components…"
        // forever, which claims progress that will never come.
        if (live) setFailedTicker(ticker);
      }
    })();
    return () => {
      live = false;
    };
  }, [ticker]);

  useEffect(() => {
    if (open == null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpenFeature(null);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

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
          <strong>not</strong> an expected return. Fundamental change does not
          precede this name&rsquo;s own drawdown (measured 2026-08-12); read
          every trajectory here as description, never as a price call.
        </div>
      </div>

      {/* Above the subscores on purpose. The band is the one block carrying a
          measured within-ticker claim (+0.0744, t 5.77); the subscore
          trajectories below it are descriptive only, so the ordering matches
          what each block is entitled to assert. */}
      {card.anchors ? (
        <div style={panelStyle} data-testid="fundamentals-anchors">
          <FundamentalAnchorBand a={card.anchors} />
        </div>
      ) : (
        <div style={panelStyle} data-testid="fundamentals-anchors-absent">
          <div style={labelStyle}>VALUATION BAND</div>
          <div
            style={{
              fontSize: 12,
              color: "var(--text-muted)",
              marginTop: 8,
              lineHeight: 1.5,
            }}
          >
            No band for this name — it has no <code>company_type</code>, so no
            valuation method is routed to it. That is a gap in our coverage, not
            a judgement about the company.
          </div>
        </div>
      )}

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
          gap: 12,
        }}
      >
        {card.subscores.map((s) => {
          const detail = stmts?.features.find((f) => f.feature === s.feature);
          if (open === s.feature) {
            return (
              <div
                key={s.feature}
                style={{ ...panelStyle, padding: 12, gridColumn: "1 / -1" }}
                data-testid={`subscore-back-${s.feature}`}
              >
                {detail && stmts ? (
                  <FundamentalCardBack
                    detail={detail}
                    periods={stmts.period_ends}
                    currency={stmts.reported_currency}
                    label={LABELS[s.feature] ?? s.feature}
                    onClose={() => setOpenFeature(null)}
                  />
                ) : (
                  <BackPlaceholder
                    failed={statementsFailed}
                    onClose={() => setOpenFeature(null)}
                  />
                )}
              </div>
            );
          }
          return (
            <SubscoreTile
              key={s.feature}
              s={s}
              dates={dates}
              onOpen={() => setOpenFeature({ ticker, feature: s.feature })}
            />
          );
        })}
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
