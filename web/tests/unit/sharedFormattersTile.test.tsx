/* @vitest-environment jsdom */
// I-105 no-visual-change proof: static markup of every component whose
// formatter or Tile moved to a shared module. The snapshots were written
// BEFORE the move; the refactor must leave them byte-identical.
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { CockpitDealerTab } from "@/app/cockpit/[ticker]/CockpitDealerTab";
import { CockpitFlowImTab } from "@/app/cockpit/[ticker]/CockpitFlowImTab";
import { CockpitSurfaceTab } from "@/app/cockpit/[ticker]/CockpitSurfaceTab";
import { StateTab } from "@/app/cockpit/[ticker]/StateTab";
import GexCurvatureChart from "@/components/shared/GexCurvatureChart";
import { GexLevelTiles } from "@/components/stock/panels/GexLevelTiles";
import { VolMetricsCard } from "@/components/stock/panels/VolMetricsCard";
import type { CockpitDealerResponse, CockpitStateResponse } from "@/lib/api";
import type { components } from "@/lib/types";
import aapl from "@/tests/fixtures/mcp/aapl_stock.json";
import spyDealer from "@/tests/fixtures/mcp/spy_cockpit_dealer.json";

const state = {
  ticker: "SPY",
  market_date: "2026-05-15",
  threshold_version: 3,
  term_state: "vol_down",
  term_classification: "event_back",
  skew_regime: "accelerated",
  vanna_conditional_reading: "grind_up",
  vanna_oi_change_bias: null,
  charm_regime: "operative_magnet",
  cluster_coverage_ok: true,
  skew_25d_zscore_180d: "-1.75",
} as unknown as CockpitStateResponse["state"];
const stateData = { state, freshness: {} } as unknown as CockpitStateResponse;

describe("I-105 markup snapshots", () => {
  it("VolMetricsCard", () => {
    expect(
      renderToStaticMarkup(
        <VolMetricsCard
          header={{
            iv: "0.53",
            rv: "0.41",
            iv_rank: "21",
            iv_percentile_30d: "52",
            implied_move_30d_perc: "0.046",
            skew_25d: "-0.0079",
            vrp: "0.42",
            vrp_signal: "rich",
            vrp_note: "IV rich vs RV — favors short premium",
          }}
        />,
      ),
    ).toMatchSnapshot();
  });

  it("GexLevelTiles (AAPL fixture)", () => {
    const report =
      aapl as unknown as components["schemas"]["SingleStockReport"];
    expect(
      renderToStaticMarkup(<GexLevelTiles report={report} />),
    ).toMatchSnapshot();
  });

  it("cockpit StateTab / SurfaceTab / FlowImTab", () => {
    expect(
      renderToStaticMarkup(<StateTab ticker="SPY" data={stateData} />),
    ).toMatchSnapshot();
    expect(
      renderToStaticMarkup(
        <CockpitSurfaceTab
          ticker="SPY"
          data={{
            ticker: "SPY",
            market_date: "2026-05-15",
            skew: [],
            term: [],
          }}
          stateData={stateData}
        />,
      ),
    ).toMatchSnapshot();
    expect(
      renderToStaticMarkup(
        <CockpitFlowImTab
          ticker="SPY"
          data={
            {
              ticker: "SPY",
              market_date: "2026-05-15",
              alerts: [
                {
                  alert_id: "a1",
                  option_chain: "SPY260515C00500000",
                  expiry: "2026-05-15",
                  strike: "500",
                  option_type: "call",
                  total_premium: "250000",
                  volume: 1000,
                  open_interest: 300,
                  created_at: "2026-05-15T15:00:00Z",
                  flow_footprint_label: "directional_whale",
                },
                {
                  alert_id: "a2",
                  option_chain: "SPY260515P00480000",
                  expiry: "2026-05-15",
                  strike: "480",
                  option_type: "put",
                  total_premium: "90000",
                  volume: 200,
                  open_interest: 50,
                  created_at: "2026-05-15T15:05:00Z",
                  flow_footprint_label: null,
                },
              ],
              implied_moves: [],
            } as never
          }
        />,
      ),
    ).toMatchSnapshot();
  });

  it("cockpit DealerTab (SPY fixture, null labels use the em dash)", () => {
    const data = spyDealer as unknown as CockpitDealerResponse;
    expect(
      renderToStaticMarkup(<CockpitDealerTab ticker="SPY" data={data} />),
    ).toMatchSnapshot();
    expect(
      renderToStaticMarkup(
        <CockpitDealerTab
          ticker="SPY"
          data={{ ...data, metrics: {} } as CockpitDealerResponse}
        />,
      ),
    ).toMatchSnapshot();
  });

  it("GexCurvatureChart axis labels", () => {
    const b = (strike: number, net_gex: number) => ({
      strike,
      call_gex: 0,
      put_gex: 0,
      net_gex,
      pct_from_spot: 0,
      tag: null,
    });
    expect(
      renderToStaticMarkup(
        <GexCurvatureChart
          profile={[
            b(90, -2_500_000),
            b(95, -3_000),
            b(100, 400),
            b(105, 4_000),
            b(110, 6_200_000),
          ]}
          spot={100}
        />,
      ),
    ).toMatchSnapshot();
  });
});
