"use client";
import { useEffect, useState } from "react";
import type { components } from "@/lib/types";
import { api } from "@/lib/api";
import { fmtDecimal, fmtPct } from "@/lib/formatters";

type Card = components["schemas"]["FundamentalCardResponse"];
type Subscore = components["schemas"]["FundamentalSubscore"];

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

function SubscoreTile({ s }: { s: Subscore }) {
  const suppressed = s.suppressed_by.length > 0;
  const value =
    s.value == null
      ? "na"
      : s.unit === "ratio"
        ? fmtPct(s.value, 1)
        : `${fmtDecimal(s.value, 2)}x`;

  return (
    <div
      style={{ ...panelStyle, padding: 12 }}
      data-testid={`subscore-${s.feature}`}
    >
      <div style={labelStyle}>{LABELS[s.feature] ?? s.feature}</div>
      <div
        style={{
          fontSize: 22,
          fontWeight: 700,
          // No ramp, no red/green. A colour scale on a raw level implies a
          // comparison, and this endpoint speaks about one name — there is no
          // cross-section here to compare it against.
          color: s.value == null ? "var(--text-muted)" : "var(--text-primary)",
          margin: "6px 0 4px",
        }}
      >
        {value}
      </div>
      {suppressed ? (
        <div style={{ fontSize: 10, color: "var(--warning)", lineHeight: 1.4 }}>
          suppressed · {s.suppressed_by.join(", ")}
        </div>
      ) : (
        <div style={{ fontSize: 10, color: "var(--text-muted)" }}>
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
            fontSize: 32,
            fontWeight: 700,
            color: "var(--text-primary)",
            margin: "8px 0 6px",
          }}
        >
          {card.composite == null ? "na" : fmtDecimal(card.composite, 2)}
        </div>
        <div
          style={{ fontSize: 11, color: "var(--text-muted)", lineHeight: 1.5 }}
        >
          Cross-sectional z-mean of the seven measured features. A sort key
          across the wide tier only — <strong>not</strong>{" "}
          an expected return,
          and not comparable at this page&rsquo;s width. Fundamental change does
          not precede this name&rsquo;s own drawdown (measured 2026-08-12); read
          the subscores as description, never as a price call.
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
          <SubscoreTile key={s.feature} s={s} />
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
            {prov.source_obs_count} source rows
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
