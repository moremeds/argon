/* @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { CockpitStateResponse } from "../../lib/api";
import { CockpitFlowImTab } from "../../app/cockpit/[ticker]/CockpitFlowImTab";
import { CockpitSurfaceTab } from "../../app/cockpit/[ticker]/CockpitSurfaceTab";
import { CockpitVrpTab } from "../../app/cockpit/[ticker]/CockpitVrpTab";
import { StateTab } from "../../app/cockpit/[ticker]/StateTab";

const stateData: CockpitStateResponse = {
  state: {
    ticker: "SPY",
    market_date: "2026-05-15",
    threshold_version: 3,
    vanna_state: "vol_down",
    charm_state: "vol_down",
    skew_state: "vol_up",
    term_state: "vol_down",
    im_state: "stale",
    flow_state: "stale",
    vrp_state: "vol_down",
    consistency_tier: "strong",
    cluster_coverage_ok: true,
    term_classification: "event_back",
    skew_25d_zscore_180d: "-1.75",
    iv_atm_30d: "0.21",
    rv_30d: "0.18",
    vrp: "0.03",
    vrp_zscore_60d: "1.42",
    implied_move_pct: "0.022",
    front_iv: "0.28",
    back_iv: "0.21",
    front_back_spread: "-0.07",
    pin_distance_sigma: "0.60",
    vrp_sign_flip_status: true,
    vrp_sign_flip_aligned_days: 30,
    vanna_conditional_reading: "grind_up",
    directional_imbalance_3d: "-250000",
    vanna_oi_change_bias: "put_oi_build",
    charm_regime: "operative_magnet",
    charm_stress_override: false,
    skew_25d_5d_change: "-0.04",
    skew_regime: "accelerated",
    skew_term_structure: "-0.02",
    single_point_bump_pct: "0.33",
    full_curve_slope_pct: "-0.12",
    term_johnson_slope_pc1: "-0.12",
    atm_straddle_mid: "8.50",
    implied_move_expected_abs: "0.018",
    implied_move_event_percentile: null,
    vrp_zscore_252d: "0.88",
  },
  freshness: {
    vanna_charm: null,
    skew: null,
    term: null,
    im_vrp: null,
    vrp_rv: null,
    oi: null,
  },
};

describe("cockpit matrix tabs", () => {
  it("renders state gate fields", () => {
    render(<StateTab ticker="SPY" data={stateData} />);

    expect(screen.getByText("CLUSTER COVERAGE")).toBeTruthy();
    expect(screen.getByText("OK")).toBeTruthy();
    expect(screen.getByText("THRESHOLD VERSION")).toBeTruthy();
    expect(screen.getByText("3")).toBeTruthy();
    expect(screen.getByText("TERM CLASSIFICATION")).toBeTruthy();
    expect(screen.getByText("EVENT BACK")).toBeTruthy();
    expect(screen.getByText("VANNA READING")).toBeTruthy();
    expect(screen.getByText("GRIND UP")).toBeTruthy();
    expect(screen.getByText("CHARM REGIME")).toBeTruthy();
    expect(screen.getByText("OPERATIVE MAGNET")).toBeTruthy();
  });

  it("renders canonical state fields on the surface tab", () => {
    render(
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
    );

    expect(screen.getByText("TERM CLASSIFICATION")).toBeTruthy();
    expect(screen.getByText("EVENT BACK")).toBeTruthy();
    expect(screen.getByText("SKEW Z 180D")).toBeTruthy();
    expect(screen.getByText("-1.75")).toBeTruthy();
    expect(screen.getByText("SKEW 5D CHANGE")).toBeTruthy();
    expect(screen.getByText("SKEW REGIME")).toBeTruthy();
    expect(screen.getByText("SINGLE BUMP")).toBeTruthy();
    expect(screen.getByText("FRONT/BACK SPREAD")).toBeTruthy();
  });

  it("renders canonical VRP z and sign-flip state on the VRP tab", () => {
    render(
      <CockpitVrpTab
        ticker="SPY"
        data={{
          ticker: "SPY",
          market_date: "2026-05-15",
          points: [
            {
              market_date: "2026-05-15",
              iv: "0.21",
              rv: "0.18",
              vrp: "0.03",
              iv_rank_1y: "0.64",
            },
          ],
        }}
        stateData={stateData}
      />,
    );

    expect(screen.getByText("VRP Z 60D")).toBeTruthy();
    expect(screen.getByText("+1.42")).toBeTruthy();
    expect(screen.getByText("SIGN FLIP")).toBeTruthy();
    expect(screen.getByText("YES 30/30")).toBeTruthy();
    expect(screen.getByText("VRP Z 252D")).toBeTruthy();
    expect(screen.getByText("+0.88")).toBeTruthy();
  });

  it("renders available flow-alert classifier inputs", () => {
    render(
      <CockpitFlowImTab
        ticker="SPY"
        data={{
          ticker: "SPY",
          market_date: "2026-05-15",
          alerts: [
            {
              alert_id: "alert-1",
              option_chain: "SPY260515C00500000",
              expiry: "2026-05-15",
              strike: "500",
              option_type: "call",
              total_premium: "250000",
              volume: 1000,
              open_interest: 300,
              total_ask_side_prem: "200000",
              total_bid_side_prem: "50000",
              created_at: "2026-05-15T15:00:00Z",
              has_sweep: true,
              has_floor: false,
              has_multileg: true,
              all_opening_trades: true,
              alert_rule: "RepeatedHits",
              flow_footprint_label: "directional_whale",
              aggressor_label_confidence: "0.75",
            },
          ],
          implied_moves: [
            {
              market_date: "2026-05-15",
              days: 7,
              volatility: "0.40",
              implied_move_perc: "0.08",
              implied_move_expected_abs: "0.063832",
              percentile: null,
            },
          ],
        }}
      />,
    );

    expect(screen.getByText("Rule")).toBeTruthy();
    expect(screen.getByText("Flags")).toBeTruthy();
    expect(screen.getByText("RepeatedHits")).toBeTruthy();
    expect(screen.getByText("SWEEP MULTI OPEN")).toBeTruthy();
    expect(screen.getByText("DIRECTIONAL WHALE")).toBeTruthy();
    expect(screen.getByText("0.75")).toBeTruthy();
    expect(screen.getByText("E|Move|")).toBeTruthy();
    expect(screen.getByText("0.0638")).toBeTruthy();
  });
});
