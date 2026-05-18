import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
}));

import { GoldCompassLayout } from "@/components/gold/GoldCompassLayout";
import type { components } from "@/lib/types";

type State = components["schemas"]["GoldStateResponse"];

const FIXTURE: State = {
  obs_date: "2026-05-17",
  computed_at: "2026-05-17T21:00:00Z",
  gauge: {
    corr_60d: "-0.04",
    corr_126d: "-0.05",
    corr_252d: "-0.07",
    corr_504d: "-0.31",
    corr_252d_returns: "-0.06",
    state: "suspended",
  },
  spot: {
    last: "4561.50",
    delta_abs: "-157.20",
    delta_pct: "-0.0332",
    high: "4615.20",
    low: "4524.30",
    open: "4615.20",
  },
  structural: {
    state_label: "structural-bid-intact",
    posture_chip: "FAVORABLE",
    cb_strategic_12m_sum_t: "210",
    cb_tactical_12m_sum_t: "12",
    cb_diversifier_12m_sum_t: "34",
    cb_52w_pct: "0.78",
    gld_holdings_t: "872.5",
    gld_30d_net_flow_t: "-12.4",
    comex_registered_oz: "17500100",
    comex_20d_roc_pct: "0.14",
    lbma_30d_momentum_t: null,
    cot_mm_net_pct: "0.72",
    cot_mm_4w_change_sigma: "0.18",
    uw_25d_skew_sigma: "1.2",
    fx_basket_dxy_z: "0.6",
    xau_cny_premium_pct: "0.004",
    gld_history: [],
    gold_history: [],
    cb_country_history: [
      {
        country_iso3: "CHN",
        country_name: "China",
        bucket: "strategic_accumulator",
        latest_reserves_t: "2313.5",
        history: [
          { obs_date: "2000-03-31", value: "395.0" },
          { obs_date: "2026-03-31", value: "2313.5" },
        ],
      },
      {
        country_iso3: "POL",
        country_name: "Poland",
        bucket: "reserve_diversifier",
        latest_reserves_t: "581.6",
        history: [
          { obs_date: "2000-03-31", value: "102.9" },
          { obs_date: "2026-03-31", value: "581.6" },
        ],
      },
    ],
    narrative_text: "Structural bid intact.",
  },
  cyclical: {
    zone_label: "moderate-trap",
    posture_chip: "SUSPENDED",
    cpi_yoy: "2.8",
    t5yifr: "2.31",
    t5yifr_pct_52w: "0.48",
    dfii10: "1.97",
    dfii10_60d_change_bps: "12",
    dxy: "102.1",
    dxy_60d_sigma: "-0.4",
    gpr_value: "371",
    gpr_pct_52w: "0.64",
    factors: { F1: -0.4, F5: 1.8 },
    two_force_text: {
      discount_rate: "tightening — would press gold",
      hedge_demand: "subdued vol — no panic bid",
    },
    narrative_text: "Cyclical posture suspended.",
  },
  valuation: {
    flag: "Severe",
    posture_chip: "STRETCHED",
    real_price_percentile: "0.92",
    gold_m2_ratio_percentile: "0.78",
    gold_oil_ratio_percentile: "0.89",
    gold_spx_ratio_percentile: "0.64",
    narrative_text: "Mean-reversion risk: SEVERE.",
  },
  inputs_used: {
    DFII10: { obs_date: "2026-05-16", as_of: "2026-05-17T00:00:00Z" },
  },
  data_freshness: [
    {
      id: "FRED",
      last_as_of: "2026-05-17T00:00:00Z",
      stale_seconds: 60,
      status: "ok",
    },
  ],
  decomposition_rows: [
    { lens: "L1", factor: "CB Δ12M", contribution: "1.4" },
    { lens: "L2", factor: "DFII10", contribution: "-0.4" },
    { lens: "L3", factor: "Gold/CPI", contribution: "1.8" },
  ],
  correlation_history: {
    gold_dfii10: [
      { obs_date: "2024-12-31", value: "-0.12" },
      { obs_date: "2025-06-30", value: "-0.04" },
    ],
    gold_dxy: [],
    gold_gpr: [],
    pre_2022_band: { mean: "-0.84", std: "0.04" },
  },
};

describe("GoldCompassLayout", () => {
  it("renders the five tiers as discrete regions", () => {
    render(<GoldCompassLayout state={FIXTURE} />);
    expect(screen.getByRole("region", { name: /kpi/i })).toBeTruthy();
    expect(screen.getByRole("region", { name: /lens 1/i })).toBeTruthy();
    expect(screen.getByRole("region", { name: /lens 2/i })).toBeTruthy();
    expect(screen.getByRole("region", { name: /lens 3/i })).toBeTruthy();
    expect(
      screen.getByRole("region", { name: /decomposition|correlation/i }),
    ).toBeTruthy();
  });

  it("renders GOLD COMPASS wordmark", () => {
    render(<GoldCompassLayout state={FIXTURE} />);
    expect(screen.getByText(/GOLD COMPASS/)).toBeTruthy();
  });

  it("labels GLD ETF flow units and source clearly", () => {
    render(<GoldCompassLayout state={FIXTURE} />);
    expect(screen.getByText("-12.4 t")).toBeTruthy();
    expect(screen.getByText(/current holdings 872.5 tonnes/)).toBeTruthy();
    expect(screen.getByText(/30D net flow/)).toBeTruthy();
  });

  it("spells out central-bank reserve units", () => {
    render(<GoldCompassLayout state={FIXTURE} />);
    expect(screen.getAllByText(/210 tonnes/).length).toBeGreaterThan(0);
    expect(screen.getByText(/TACTICAL 12 tonnes/)).toBeTruthy();
    expect(screen.getByText(/DIVERSIFIER 34 tonnes/)).toBeTruthy();
  });

  it("labels converted UW flow clearly when holdings are unavailable", () => {
    const state: State = {
      ...FIXTURE,
      structural: {
        ...FIXTURE.structural,
        gld_holdings_t: null,
        gld_30d_net_flow_t: "-11.0038",
      },
    };
    render(<GoldCompassLayout state={state} />);
    expect(screen.getByText("-11.0 t")).toBeTruthy();
    expect(screen.getByText(/converted from UW GLD share flow/)).toBeTruthy();
    expect(screen.getByText(/holdings unavailable/)).toBeTruthy();
  });

  it("shows central-bank country reserve toggles", () => {
    render(<GoldCompassLayout state={FIXTURE} />);
    expect(screen.getByText(/Central bank reserves by country/)).toBeTruthy();
    const chinaToggle = screen.getByLabelText("Toggle China");
    expect(chinaToggle).toBeTruthy();
    fireEvent.click(chinaToggle);
    expect((chinaToggle as HTMLInputElement).checked).toBe(false);
  });

  it("uses posture language only (no buy/sell/long/short)", () => {
    const { container } = render(<GoldCompassLayout state={FIXTURE} />);
    const text = (container.textContent ?? "").toLowerCase();
    expect(text).not.toMatch(/\bbuy\b/);
    expect(text).not.toMatch(/\bsell\b/);
    expect(text).not.toMatch(/\bposition size\b/);
    expect(text).not.toMatch(/\bpredicted return\b/);
  });
});
