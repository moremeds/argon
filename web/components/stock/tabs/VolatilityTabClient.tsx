"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import type {
  RegimeDealerResponse,
  RegimeVcgResponse,
  VolatilitySeriesResponse,
} from "@/lib/api";

import { DivergenceOverlay } from "../panels/DivergenceOverlay";
import { HvIvChart } from "../panels/HvIvChart";
import { IvOfIvChart } from "../panels/IvOfIvChart";
import { IvPercentileDistribution } from "../panels/IvPercentileDistribution";
import { RegimeQuadrantChart } from "../panels/RegimeQuadrantChart";
import { RvSpyCorrChart } from "../panels/RvSpyCorrChart";
import { SmileChart } from "../panels/SmileChart";
import { TermStructureChart } from "../panels/TermStructureChart";
import { VolMetricsCard } from "../panels/VolMetricsCard";
import { VolatilityRegimePanel } from "../panels/VolatilityRegimePanel";
import { VrpSpreadPanel } from "../panels/VrpSpreadPanel";

// Spec §7.4: poll every 5s for up to 60s while backfill_status === 'running'.
const POLL_INTERVAL_MS = 5_000;
const POLL_BUDGET_MS = 60_000;
type RegimeState = {
  ticker: string;
  data: RegimeDealerResponse | null;
};

export function VolatilityTabClient({
  ticker,
  initial,
}: {
  ticker: string;
  initial: VolatilitySeriesResponse;
}) {
  const [series, setSeries] = useState<VolatilitySeriesResponse>(initial);
  const [regimeState, setRegimeState] = useState<RegimeState>({
    ticker,
    data: null,
  });
  const [vcg, setVcg] = useState<RegimeVcgResponse | null>(null);

  // Fetch /regime/dealer client-side. Clear state on ticker change so the
  // previous ticker's panel doesn't briefly flash while the new one loads.
  useEffect(() => {
    let cancelled = false;
    api
      .regimeDealer(ticker)
      .then((r) => {
        if (!cancelled) setRegimeState({ ticker, data: r });
      })
      .catch(() => {
        if (!cancelled) setRegimeState({ ticker, data: null });
      });
    return () => {
      cancelled = true;
    };
  }, [ticker]);

  // Macro VCG is index-wide, not per-ticker — fetch once.
  useEffect(() => {
    let cancelled = false;
    api
      .regimeVcg()
      .then((r) => {
        if (!cancelled) setVcg(r);
      })
      .catch(() => {
        if (!cancelled) setVcg(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (series.backfill_status !== "running") return;
    let elapsed = 0;
    const id = setInterval(async () => {
      elapsed += POLL_INTERVAL_MS;
      try {
        const next = await api.volatilitySeries(ticker);
        setSeries(next);
        if (next.backfill_status !== "running" || elapsed >= POLL_BUDGET_MS) {
          clearInterval(id);
        }
      } catch {
        if (elapsed >= POLL_BUDGET_MS) clearInterval(id);
      }
    }, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [ticker, series.backfill_status]);

  const banner =
    series.backfill_status === "running"
      ? { text: "Building 1-year history… (≤30s)", color: "var(--warning)" }
      : series.backfill_status === "failed"
        ? {
            text: "Backfill failed — retry by refreshing.",
            color: "var(--negative)",
          }
        : null;
  const regime = regimeState.ticker === ticker ? regimeState.data : null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <VolatilityRegimePanel data={regime} vcg={vcg} />
      <VolMetricsCard header={series.header} />

      {banner && (
        <div
          style={{
            padding: 8,
            background: "var(--bg-panel)",
            border: `1px dashed ${banner.color}`,
            borderRadius: 4,
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            color: banner.color,
          }}
        >
          {banner.text}
        </div>
      )}

      <div
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 9,
          letterSpacing: 1,
          color: "var(--text-muted)",
          textTransform: "uppercase",
          marginTop: 4,
        }}
      >
        Analytical time series
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <IvOfIvChart data={series.iv_of_iv} />
        <RvSpyCorrChart data={series.rv_spy_corr} />
        <RegimeQuadrantChart data={series.regime_quadrant} />
        <DivergenceOverlay
          data={series.divergence}
          headline={series.divergence_headline}
        />
      </div>

      <div
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 9,
          letterSpacing: 1,
          color: "var(--text-muted)",
          textTransform: "uppercase",
          marginTop: 4,
        }}
      >
        Today&apos;s snapshot
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <TermStructureChart data={series.term_structure} />
        <SmileChart data={series.smile} spot={series.spot} />
        <HvIvChart data={series.hv_iv_history} />
        <IvPercentileDistribution data={series.iv_percentile_distribution} />
      </div>

      <VrpSpreadPanel
        data={series.vrp_spread}
        headline={series.vrp_spread_headline}
      />
    </div>
  );
}
