"use client";

import GrgDivergenceChart from "./GrgDivergenceChart";
import InfoTooltip from "./InfoTooltip";
import { useGrgLive, type GrgResponse } from "@/lib/regime/useGrgLive";
import { AssetCard } from "./grg/AssetCard";
import { EventsColumn } from "./grg/EventsColumn";
import { GatesPanel } from "./grg/GatesPanel";
import { GrgHero } from "./grg/GrgHero";
import { GrgTopBottom } from "./grg/GrgTopBottom";
import { BACKTEST_HELP, backtestSummary, pairStateColor } from "./grg/format";

export {
  assetStateHelp,
  fmtGex,
  gateColor,
  pairStateColor,
  shortState,
  sigmaColor,
} from "./grg/format";

export function GrgSubTabView({ data }: { data: GrgResponse | null }) {
  if (!data || data.status === "empty" || !data.assets) {
    return (
      <div className="regime-empty" data-testid="grg-empty">
        No GRG snapshot yet. The scanner runs every 15 min (market hours +
        post-close settlement).
      </div>
    );
  }

  const signal = data.signal;
  const top_bottom = data.top_bottom;
  // Generated types mark default-valued fields optional. A non-empty snapshot
  // always carries signal + top_bottom; narrow them here (mirrors VcgSubTab).
  if (!signal || !top_bottom) {
    return (
      <div className="regime-empty" data-testid="grg-empty">
        No GRG snapshot yet. The scanner runs every 15 min (market hours +
        post-close settlement).
      </div>
    );
  }
  const assets = data.assets; // non-null: guarded by the early return above
  const gates = data.gates ?? [];
  const history = data.history ?? [];
  const tops = data.events?.tops ?? [];
  const bottoms = data.events?.bottoms ?? [];
  const eventStats = data.events?.stats;
  const backtestLine = backtestSummary(eventStats);
  const topSide = top_bottom.top ?? { active: false, copy: "" };
  const botSide = top_bottom.bottom ?? { active: false, copy: "" };
  const stateColor = pairStateColor(signal.state);

  return (
    <div
      className="section gex-panel"
      data-testid="grg-panel"
      style={{ padding: 16 }}
    >
      {/* Hero */}
      <GrgHero
        data={data}
        signal={signal}
        assets={assets}
        stateColor={stateColor}
      />

      {/* Asset cards + chart. Cards are capped narrow so the divergence
          chart takes the rest of the row. */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(220px, 280px) 1fr",
          gap: 16,
          marginTop: 16,
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <AssetCard asset={assets.SPY} />
          <AssetCard asset={assets.TLT} />
        </div>
        <GrgDivergenceChart history={history} tops={tops} bottoms={bottoms} />
      </div>

      {/* Backtest caveat for the chart markers — they LEAD the turn. */}
      <div
        data-testid="grg-backtest-caption"
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 6,
          marginTop: 6,
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          letterSpacing: "0.04em",
          color: "var(--text-muted)",
        }}
      >
        <span>
          {backtestLine ||
            "Top/bottom markers are gate-confirmed watch signals — early-warning, not the exact turn."}
        </span>
        <InfoTooltip
          text={BACKTEST_HELP}
          ariaLabel="GRG top/bottom backtest"
          triggerTestId="grg-backtest-info"
          contentTestId="grg-backtest-help"
        />
      </div>

      {/* Top / Bottom identification */}
      <GrgTopBottom topSide={topSide} botSide={botSide} />

      {/* Recent gate-confirmed tops / bottoms (YTD history of the signal) */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 16,
          marginTop: 16,
        }}
      >
        <EventsColumn
          title="Recent Top-Watches"
          testid="grg-recent-tops"
          events={tops}
          emptyCopy="No gate-confirmed top-watches year-to-date."
        />
        <EventsColumn
          title="Recent Bottom-Watches"
          testid="grg-recent-bottoms"
          events={bottoms}
          emptyCopy="No gate-confirmed bottom-watches year-to-date."
        />
      </div>
      <div
        style={{
          marginTop: 6,
          fontSize: 10,
          fontFamily: "var(--font-mono)",
          color: "var(--text-muted)",
        }}
      >
        Gate-confirmed TOP_WATCH / BOTTOM_WATCH days, YTD. Spot-vs-flip excluded
        — UW history carries no per-day gamma flip.
      </div>

      {/* Gates */}
      <div style={{ marginTop: 16 }}>
        <GatesPanel gates={gates} />
      </div>
    </div>
  );
}

export default function GrgSubTab() {
  const { data } = useGrgLive();
  return <GrgSubTabView data={data} />;
}
