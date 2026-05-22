import type { components } from "@/lib/types";

type Snapshot = components["schemas"]["RatesSnapshotResponse"];

export const TENORS = [
  "1M",
  "3M",
  "6M",
  "1Y",
  "2Y",
  "3Y",
  "5Y",
  "7Y",
  "10Y",
  "20Y",
  "30Y",
];

export const SNAPSHOT: Snapshot = {
  as_of: "2026-05-20",
  computed_at: "2026-05-21T11:31:06Z",
  summary: [
    { label: "2Y", value: 3.95, unit: "%", delta_1d: -2, status: "ok" },
    { label: "5Y", value: 4.12, unit: "%", delta_1d: 1, status: "ok" },
    { label: "10Y", value: 4.52, unit: "%", delta_1d: 3, status: "ok" },
    { label: "30Y", value: 4.87, unit: "%", delta_1d: 2, status: "ok" },
    { label: "2s10s", value: 57, unit: "bps", delta_1d: 5, status: "ok" },
    { label: "5s30s", value: 75, unit: "bps", delta_1d: 1, status: "ok" },
  ],
  curve: {
    points: TENORS.map((tenor, index) => ({
      tenor,
      series_id: `DGS${tenor}`,
      value: 3.8 + index * 0.08,
      delta_1d_bps: index - 5,
      delta_1w_bps: index,
      delta_1m_bps: index * 2,
      obs_date: "2026-05-20",
      status: "ok",
    })),
    slopes: [
      { label: "2s10s", value_bps: 57, status: "ok" },
      { label: "5s30s", value_bps: 75, status: "ok" },
      { label: "3m10y", value_bps: 85, status: "ok" },
      { label: "2s5s10s butterfly", value_bps: -16, status: "ok" },
    ],
  },
  decomposition: {
    nominal_10y: 4.52,
    real_10y: 2.12,
    breakeven_10y: 2.4,
    forward_inflation_5y5y: 2.28,
    term_forward_compensation: 0.12,
    status: "ok",
    attribution: [
      {
        window: "1D",
        nominal_10y_bps: 3,
        real_10y_bps: 2,
        breakeven_10y_bps: 1,
        residual_bps: 0,
        driver: "Real rate",
        status: "ok",
      },
      {
        window: "1W",
        nominal_10y_bps: 15,
        real_10y_bps: 10,
        breakeven_10y_bps: 5,
        residual_bps: 0,
        driver: "Real rate",
        status: "ok",
      },
      {
        window: "1M",
        nominal_10y_bps: 35,
        real_10y_bps: 23,
        breakeven_10y_bps: 12,
        residual_bps: 0,
        driver: "Real rate",
        status: "ok",
      },
      {
        window: "YTD",
        nominal_10y_bps: 42,
        real_10y_bps: 19,
        breakeven_10y_bps: 23,
        residual_bps: 0,
        driver: "Breakeven",
        status: "ok",
      },
    ],
  },
  scorecard: {
    composite_score: 0.1,
    duration_stance: "NEUTRAL",
    curve_score: -0.25,
    curve_stance: "FLAT",
    groups: [
      {
        id: "policy",
        label: "Monetary Policy",
        weight: 25,
        score: -1,
        status: "ok",
        factors: [
          {
            label: "Policy pressure",
            value: "EFFR above 2Y",
            score: -1,
            status: "ok",
            source: "FRED",
          },
        ],
      },
      {
        id: "macro",
        label: "Macro Fundamentals",
        weight: 25,
        score: 1,
        status: "ok",
        factors: [
          {
            label: "Growth impulse",
            value: "Curve improving",
            score: 1,
            status: "ok",
            source: "FRED",
          },
        ],
      },
    ],
  },
  policy: {
    target_range: null,
    effr: 4.33,
    sofr: 4.31,
    plumbing: [
      { label: "RRP", value: 142.5, unit: "B", delta_1d: null, status: "ok" },
    ],
    status: "partial",
  },
  supply: {
    auctions: [],
    notes: ["Treasury auction feed not wired in Phase 1."],
    status: "missing",
  },
  positioning: { rows: [], status: "missing" },
  cross_market: {
    rows: [
      {
        label: "10Y real",
        value: 2.12,
        unit: "%",
        delta_1d: null,
        status: "ok",
      },
    ],
    status: "partial",
  },
  events: [],
  synthesis: {
    duration_view: "Neutral until the live FRED curve breaks range.",
    curve_view: "Curve still biased flatter.",
    risks: ["Auction and positioning feeds are unavailable."],
  },
  source_freshness: [
    {
      id: "DGS10",
      label: "10Y Treasury",
      latest_obs_date: "2026-05-20",
      last_seen_at: "2026-05-21T11:31:06Z",
      status: "stale",
    },
  ],
};
