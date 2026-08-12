"use client";
import { useEffect, useState } from "react";
import type { components } from "@/lib/types";
import { api } from "@/lib/api";
import { fmtDecimal } from "@/lib/formatters";
import { FundamentalAnchorBand } from "../panels/FundamentalAnchorBand";
import { FundamentalBackPlaceholder } from "../panels/FundamentalBackPlaceholder";
import { FundamentalCardBack } from "../panels/FundamentalCardBack";
import { FundamentalRevenueCard } from "../panels/FundamentalRevenueCard";
import { FundamentalSparkline } from "../panels/FundamentalSparkline";
import { SubscoreTile, PercentileTag } from "../panels/FundamentalSubscoreTile";
import {
  LABELS,
  backPanelStyle,
  labelStyle,
  panelStyle,
} from "../panels/fundamentalShared";

type Card = components["schemas"]["FundamentalCardResponse"];
type Statements = components["schemas"]["FundamentalStatementsResponse"];

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
                style={backPanelStyle}
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
                  <FundamentalBackPlaceholder
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

        <FundamentalRevenueCard
          detail={stmts?.features.find((f) => f.feature === "revenue_earnings")}
          periods={stmts?.period_ends ?? []}
          currency={stmts?.reported_currency ?? null}
          open={open === "revenue_earnings"}
          failed={statementsFailed}
          onOpen={() =>
            setOpenFeature({ ticker, feature: "revenue_earnings" })
          }
          onClose={() => setOpenFeature(null)}
        />
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
