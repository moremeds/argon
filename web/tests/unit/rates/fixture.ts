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
    clarida_model_date: "2026-05-01",
    model_real_yield_10y: 1.63,
    expected_short_real_rate_10y: 0.4,
    expected_short_inflation_10y: 2.48,
    real_term_premium_10y: 1.23,
    inflation_risk_premium_10y: 0.35,
    model_nominal_10y: 4.46,
    fred_model_residual_10y: 0.06,
    model_source: "Cleveland Fed Inflation Expectations",
    model_url: "https://www.clevelandfed.org/indicators-and-data/inflation-expectations",
    status: "ok",
    attribution: [
      {
        window: "1D",
        nominal_10y_bps: 3,
        real_10y_bps: 2,
        breakeven_10y_bps: 1,
        residual_bps: 0,
        model_nominal_10y_bps: 0,
        expected_short_real_bps: 0,
        expected_short_inflation_bps: 0,
        real_term_premium_bps: 0,
        inflation_risk_premium_bps: 0,
        fred_model_residual_bps: 3,
        driver: "Real rate",
        status: "ok",
      },
      {
        window: "1W",
        nominal_10y_bps: 15,
        real_10y_bps: 10,
        breakeven_10y_bps: 5,
        residual_bps: 0,
        model_nominal_10y_bps: 0,
        expected_short_real_bps: 0,
        expected_short_inflation_bps: 0,
        real_term_premium_bps: 0,
        inflation_risk_premium_bps: 0,
        fred_model_residual_bps: 15,
        driver: "Real rate",
        status: "ok",
      },
      {
        window: "1M",
        nominal_10y_bps: 35,
        real_10y_bps: 23,
        breakeven_10y_bps: 12,
        residual_bps: 0,
        model_nominal_10y_bps: 15.3,
        expected_short_real_bps: 0,
        expected_short_inflation_bps: 5.7,
        real_term_premium_bps: 3.9,
        inflation_risk_premium_bps: 5.7,
        fred_model_residual_bps: 19.7,
        driver: "FRED residual",
        status: "ok",
      },
      {
        window: "YTD",
        nominal_10y_bps: 42,
        real_10y_bps: 19,
        breakeven_10y_bps: 23,
        residual_bps: 0,
        model_nominal_10y_bps: 30,
        expected_short_real_bps: -2,
        expected_short_inflation_bps: 15,
        real_term_premium_bps: 8,
        inflation_risk_premium_bps: 9,
        fred_model_residual_bps: 12,
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
    implied_path: [
      {
        meeting_date: "2026-06-17",
        label: "6/17",
        probability: 53.9,
        stance: "HOLD",
        target_range: "3.50-3.75%",
        source: "Frenzy Capital Fed Watch",
        status: "ok",
      },
      {
        meeting_date: "2026-07-29",
        label: "7/29",
        probability: 53.9,
        stance: "HOLD",
        target_range: "3.50-3.75%",
        source: "Frenzy Capital Fed Watch",
        status: "ok",
      },
    ],
    path_read:
      "Frenzy Capital Fed Watch assigns 53.9% to hold at the next meeting.",
    plumbing: [
      {
        label: "ON RRP",
        value: 0.025,
        unit: "$T",
        qualifier: "near-zero ON RRP",
        status: "ok",
      },
    ],
    status: "partial",
  },
  supply: {
    recent_auctions: [
      {
        cusip: "912810UL0",
        security_type: "Bond",
        security_term: "30-Year",
        auction_date: "2026-05-14",
        issue_date: "2026-05-15",
        offering_amount: 25,
        high_rate: 5.046,
        bid_to_cover: 2.3,
        direct_bidder_pct: 20.3,
        indirect_bidder_pct: 56.5,
        primary_dealer_pct: 23.2,
        tail_indicator: "long-end",
        source_url:
          "https://fiscaldata.treasury.gov/static-data/published-reports/auctions-query/results/R_20260514_1.pdf",
        status: "ok",
      },
    ],
    fiscal: [
      {
        label: "Public debt",
        value: 31.37,
        unit: "$T",
        status: "ok",
      },
      {
        label: "TGA",
        value: 0.78,
        unit: "$T",
        status: "ok",
      },
    ],
    notes: [],
    supply_read:
      "TreasuryDirect auction results show long-end auction demand is soft; FiscalData public debt is $31.37T and TGA is $0.78T.",
    status: "ok",
  },
  positioning: {
    rows: [
      {
        label: "Leveraged funds · long end",
        value: -1194445,
        unit: "contracts",
        status: "ok",
      },
      {
        label: "Asset managers · long end",
        value: 1300752,
        unit: "contracts",
        status: "ok",
      },
    ],
    details: [
      {
        contract_code: "043602",
        contract_name: "UST 10Y NOTE",
        tenor_bucket: "10Y",
        obs_date: "2026-05-19",
        release_date: "2026-05-22",
        open_interest: 4544233,
        dealer_net: -97229,
        dealer_net_pct_oi: -2.1,
        asset_mgr_net: 1300752,
        asset_mgr_net_pct_oi: 28.6,
        lev_money_net: -1194445,
        lev_money_net_pct_oi: -26.3,
        source_url: "https://publicreporting.cftc.gov/resource/gpe5-46if.json",
        status: "ok",
      },
    ],
    positioning_read:
      "CFTC TFF 2026-05-22: leveraged funds are 1,194,445 contracts short on long-end Treasury futures, asset managers are 1,300,752 contracts long, and the basis proxy is 1,194,445 contracts long.",
    status: "ok",
  },
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
    risks: ["Auction and TIC feeds are unavailable."],
  },
  source_freshness: [
    {
      id: "DGS10",
      label: "10Y Treasury",
      latest_obs_date: "2026-05-20",
      last_seen_at: "2026-05-21T11:31:06Z",
      status: "stale",
    },
    {
      id: "CLEVE_EXPECTED_INFLATION_10Y",
      label: "Cleveland Fed 10Y expected inflation",
      latest_obs_date: "2026-05-01",
      last_seen_at: "2026-05-21T11:31:06Z",
      status: "partial",
    },
  ],
};

// ---------------------------------------------------------------------------
// MC2 fixtures.
//
// Every policy-path number below was produced by this repo's own parsers over the
// committed official fixtures in tests/fixtures/macro/, not written by hand:
//
//   actual               fomc_statement_2026_06.{html,pdf}  parse_fomc_statement()
//   committee_projection fed_sep_2026_06.{html,pdf}         parse_sep_release()
//   dealer_expectations  nyfed_sme_2026_06.{xlsx,pdf}       parse_sme_release()
//
// (bytes under tests/fixtures/macro/; parsers under src/uw_scan/sources/. Feed each
// file to its <Source>SourceBundle.from_bytes() and the parser prints these values.)
//
// The market-implied lane is deliberately absent: Frenzy is an optional, default-off
// third-party shadow and this repo commits no fixture for it. Rendering a partial
// comparison is a case the UI has to get right anyway.
// ---------------------------------------------------------------------------

export type PolicyComparison = components["schemas"]["PolicyComparison"];
export type MacroStateSummary = components["schemas"]["MacroStateSummary"];

const OFFICIAL_FRESHNESS = {
  status: "ok" as const,
  last_attempt_at: "2026-06-18T00:00:00Z",
  last_success_at: "2026-06-18T00:00:00Z",
  consecutive_failures: 0,
  releases_discovered: 4,
  releases_succeeded: 4,
  releases_failed: 0,
  release_failures: [],
};

export const POLICY_COMPARISON: PolicyComparison = {
  as_of: "2026-06-18T00:00:00Z",
  actual: {
    kind: "actual",
    freshness: { ...OFFICIAL_FRESHNESS, source: "fomc_statement" },
    path: {
      kind: "actual",
      source: "fomc_statement",
      source_kind: "official",
      source_record_id: "fomc-statement:monetary20260617a",
      published_at: "2026-06-17T18:00:00Z",
      available_at: "2026-06-17T18:00:00Z",
      cost_class: "free_official",
      delay_status: "not_applicable",
      points: [
        {
          horizon: "current",
          horizon_date: "2026-06-17",
          rate_percent: "3.625",
          target_range_lower_percent: "3.5",
          target_range_upper_percent: "3.75",
          action: "Hold",
          // The real statement prints a 12-0 tally and names nobody. That is why
          // voter_names_stated exists: an empty voted_against here means "no
          // dissenter was NAMED", not "the committee was unanimous".
          vote_status: "stated",
          vote_split: "12-0",
          voted_for: [],
          voted_against: [],
          voter_names_stated: false,
          participant_distribution: [],
          probability_distribution: [],
        },
      ],
      evidence_refs: [],
    },
  },
  committee_projection: {
    kind: "committee_projection",
    freshness: { ...OFFICIAL_FRESHNESS, source: "fed_sep" },
    path: {
      kind: "committee_projection",
      source: "fed_sep",
      source_kind: "official",
      source_record_id: "fed-sep:fomcprojtabl20260617",
      published_at: "2026-06-17T18:00:00Z",
      available_at: "2026-06-17T18:00:00Z",
      cost_class: "free_official",
      delay_status: "not_applicable",
      points: [
        {
          horizon: "2026",
          rate_percent: "3.8",
          central_tendency_lower_percent: "3.6",
          central_tendency_upper_percent: "4.1",
          range_lower_percent: "3.4",
          range_upper_percent: "4.4",
          participant_distribution: [
            { rate_percent: "3.375", participant_count: 1 },
            { rate_percent: "3.625", participant_count: 8 },
            { rate_percent: "3.875", participant_count: 3 },
            { rate_percent: "4.125", participant_count: 5 },
            { rate_percent: "4.375", participant_count: 1 },
          ],
          probability_distribution: [],
          voted_for: [],
          voted_against: [],
        },
        {
          horizon: "2027",
          rate_percent: "3.6",
          central_tendency_lower_percent: "3.1",
          central_tendency_upper_percent: "3.9",
          range_lower_percent: "2.9",
          range_upper_percent: "4.4",
          participant_distribution: [],
          probability_distribution: [],
          voted_for: [],
          voted_against: [],
        },
      ],
      evidence_refs: [],
    },
  },
  dealer_expectations: {
    kind: "dealer_expectations",
    freshness: { ...OFFICIAL_FRESHNESS, source: "nyfed_sme" },
    path: {
      kind: "dealer_expectations",
      source: "nyfed_sme",
      source_kind: "official",
      source_record_id: "nyfed-sme:2026-06:Dealer",
      // The workbook states no publication instant, so availability is the fetch.
      published_at: null,
      available_at: "2026-06-18T00:00:00Z",
      cost_class: "free_official",
      delay_status: "not_applicable",
      points: [
        {
          horizon: "Jun. 16-17 2026",
          horizon_date: "2026-06-17",
          rate_percent: "3.63",
          p25_percent: "3.63",
          p75_percent: "3.63",
          respondent_count: 26,
          participant_distribution: [],
          probability_distribution: [],
          voted_for: [],
          voted_against: [],
        },
        {
          horizon: "Dec. 8-9 2026",
          horizon_date: "2026-12-09",
          rate_percent: "3.63",
          p25_percent: "3.44",
          p75_percent: "3.63",
          respondent_count: 26,
          participant_distribution: [],
          probability_distribution: [],
          voted_for: [],
          voted_against: [],
        },
      ],
      evidence_refs: [],
    },
  },
  market_implied: {
    kind: "market_implied",
    missing_reason:
      "Frenzy Capital Fed Watch is an optional third-party shadow and is not enabled.",
    freshness: {
      source: "frenzy_fed_watch",
      status: "missing",
      last_attempt_at: null,
      last_success_at: null,
      consecutive_failures: 0,
      releases_discovered: 0,
      releases_succeeded: 0,
      releases_failed: 0,
      release_failures: [],
    },
  },
  contradictions: [
    "Committee projection median (3.8%) sits above the dealer median (3.63%) for 2026.",
  ],
};

/**
 * A path carrying a non-publisher source. Representable in the contract, so the UI has
 * to refuse it rather than assume upstream never emits one. No market value is invented
 * here — the point is precisely that the lane's numbers must not be shown.
 */
export const COMPARISON_WITH_REJECTED_PATH: PolicyComparison = {
  ...POLICY_COMPARISON,
  actual: {
    ...POLICY_COMPARISON.actual,
    path: {
      ...POLICY_COMPARISON.actual.path!,
      source: "demo_seed",
      source_kind: "mock",
    },
  },
};

export const POLICY_RATES_STATE: MacroStateSummary = {
  domain: "policy_rates",
  as_of: "2026-06-18T00:00:00Z",
  computed_at: "2026-06-18T00:10:00Z",
  engine_version: "policy_rates/1",
  state: "ON_HOLD",
  direction: "FLAT",
  confidence: "0.62",
  freshness: "fresh",
  age_hours: 0,
  velocity: [
    {
      metric: "target_range_midpoint_change",
      value: "0.00",
      unit: "pp",
      window_months: 3,
    },
    {
      metric: "ten_year_real_yield_change",
      unit: "pp",
      window_months: 3,
      unavailable_reason: "DFII10 has no observation in force at this instant.",
    },
  ],
  confidence_reasons: [
    {
      term: "coverage",
      value: "0.75",
      detail: "3 of 4 policy paths carry a release.",
      kind: "multiplicand",
    },
    {
      term: "freshness",
      value: "0.92",
      detail: "Newest load-bearing observation is 1 day old.",
      kind: "multiplicand",
    },
  ],
  contradictions: [
    {
      rule: "committee_above_dealers",
      detail:
        "The SEP 2026 median is 17bp above the dealer median for the same year.",
    },
  ],
  notes: ["Market-implied path absent; the state does not stand on one."],
  evidence_count: 9,
  detail_path: "/api/macro/rates",
};

export const STALE_POLICY_RATES_STATE: MacroStateSummary = {
  ...POLICY_RATES_STATE,
  freshness: "stale",
  age_hours: 96,
};
