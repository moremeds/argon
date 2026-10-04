"use client";

import { Shield, Zap } from "lucide-react";

import { VcgHistorySection } from "./vcg/VcgHistorySection";
import VcgStressHistorySection from "./vcg/VcgStressHistorySection";
import { type VcgSignal } from "@/lib/regime/useVcg";
import { useVcgLive, type VcgLiveResponse } from "@/lib/regime/useVcgLive";
import { useVcgDaily, type VcgDailyEntry } from "@/lib/regime/useVcgSeries";
import VcgZScoreHistoryChart from "./vcg/VcgZScoreHistoryChart";
import VcgSeriesGrids from "./vcg/VcgSeriesGrids";
import VcgSignalStrip from "./vcg/VcgSignalStrip";
import VcgSignalDetail from "./vcg/VcgSignalDetail";
import { interpretationColor, interpretationLabel } from "./vcg/format";

/* ─── Main view (1:1 mirror of xenon VcgPanel) ───────────────── */

export function VcgSubTabView({
  data,
  daily,
  onSyncNow,
  syncing = false,
}: {
  data: VcgLiveResponse | null;
  /** 90d daily history rows — drives the in-card sparklines. */
  daily?: VcgDailyEntry[] | null;
  onSyncNow?: () => void;
  syncing?: boolean;
}) {
  if (
    !data ||
    data.status === "empty" ||
    (!data.signal?.vcg && data.signal?.vcg !== 0)
  ) {
    return (
      <div className="section gex-panel">
        <div className="section-header">
          <div className="section-title">
            <Zap size={14} />
            Volatility-Credit Gap (VCG)
          </div>
        </div>
        <div className="section-body">
          <div className="regime-empty" data-testid="vcg-empty-state">
            <Shield size={32} strokeWidth={1} />
            <p>
              No VCG data available. Click Sync Now to run a scan for{" "}
              {data?.credit_proxy ?? "HYG"}.
            </p>
            {onSyncNow && (
              <button
                type="button"
                onClick={onSyncNow}
                disabled={syncing}
                data-testid="vcg-sync-now"
                style={{
                  marginTop: "12px",
                  padding: "6px 14px",
                  fontFamily: "var(--font-mono)",
                  fontSize: "11px",
                  letterSpacing: "0.08em",
                  textTransform: "uppercase",
                  background: "var(--bg-panel-raised, var(--bg-panel))",
                  border: "1px solid var(--border-dim, var(--line-grid))",
                  color: "var(--text-primary)",
                  cursor: syncing ? "default" : "pointer",
                  opacity: syncing ? 0.6 : 1,
                }}
              >
                {syncing ? "Syncing…" : "Sync Now"}
              </button>
            )}
          </div>
        </div>
      </div>
    );
  }

  const sig: VcgSignal = data.signal;
  const attr = sig.attribution ?? {
    vvix_pct: 0,
    vix_pct: 0,
    vvix_component: 0,
    vix_component: 0,
    model_implied: 0,
  };
  const interpColor = interpretationColor(sig.interpretation);
  const lastSync = data.scan_time;
  const history = data.history ?? [];

  // Full fetched window (oldest → newest) — the z-score history chart ranges
  // over all of it. The in-card sparklines stay at their documented 90d, so
  // widening the fetch for the chart doesn't silently restyle them.
  const dailyRows = daily ?? [];
  const sparkRows = dailyRows.slice(-90);
  const dseries = (k: keyof VcgDailyEntry): (number | null)[] =>
    sparkRows.map((r) => {
      const v = r[k];
      return typeof v === "number" && Number.isFinite(v) ? v : null;
    });

  return (
    <div className="section gex-panel" data-testid="vcg-subtab">
      <div className="section-header">
        <div className="section-title">
          <Zap size={14} />
          Volatility-Credit Gap (VCG)
        </div>
      </div>
      <div className="section-body regime-panel">
        {/* ── Signal strip ───────────────────────────────────── */}
        <VcgSignalStrip
          data={data}
          sig={sig}
          interpColor={interpColor}
          lastSync={lastSync}
          dseries={dseries}
        />

        {/* ── Signal Detail + Attribution ─────────────────────── */}
        <VcgSignalDetail sig={sig} attr={attr} interpColor={interpColor} />

        {/* ── Z-score history (bars + monotone curve, range-selectable) ── */}
        <VcgZScoreHistoryChart
          rows={dailyRows}
          interpretation={interpretationLabel(sig.interpretation)}
        />

        {/* ── Intraday small-multiples grid (basis='live' rows) ── */}
        <VcgSeriesGrids />

        {/* ── History table (sortable, folded by default) ─────── */}
        <VcgHistorySection
          history={history}
          creditProxy={data.credit_proxy ?? "HYG"}
        />

        {/* ── All-time stress history (v2 backtest) ───────────── */}
        <VcgStressHistorySection />
      </div>
    </div>
  );
}

export default function VcgSubTab() {
  const { data, syncing, syncNow } = useVcgLive();
  // 365 = the API's `days` ceiling. Feeds the z-score chart's 6M/ALL ranges;
  // the sparklines slice back to 90 downstream.
  const { data: daily } = useVcgDaily(365);
  return (
    <VcgSubTabView
      data={data}
      daily={daily?.rows ?? null}
      syncing={syncing}
      onSyncNow={syncNow}
    />
  );
}
