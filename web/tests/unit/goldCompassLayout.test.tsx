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
    // What the router actually sends: both halves are hardcoded em-dashes with no
    // producer anywhere. The panel that rendered them is gone; the field stays for
    // contract stability, so the fixture states the real value rather than prose the
    // API cannot emit.
    two_force_text: { discount_rate: "—", hedge_demand: "—" },
    narrative_text: "Cyclical posture suspended.",
  },
  valuation: {
    flag: "Severe",
    posture_chip: "STRETCHED",
    real_price_percentile: "0.92",
    gold_m2_ratio_percentile: "0.78",
    // Declared on the model, never assigned by any producer -- see models/gold.py.
    gold_oil_ratio_percentile: null,
    gold_spx_ratio_percentile: "0.64",
    narrative_text: "Mean-reversion risk: SEVERE.",
  },
  inputs_used: {
    DFII10: {
      obs_date: "2026-05-16",
      as_of: "2026-05-17T00:00:00Z",
      lens: ["L2"],
      causal_role: "decomposition_component",
      source: "fred",
      row_count: 1289,
      required: true,
      omission_reason: null,
    },
    // An input that was declared and deliberately NOT read. The manifest used to omit
    // these entirely and the router dropped anything without an obs_date, so a reader
    // could not tell "not consulted" from "nothing to say".
    fx: {
      obs_date: null,
      as_of: null,
      lens: ["L1"],
      causal_role: "curve",
      source: "none",
      row_count: 0,
      required: false,
      omission_reason:
        "compute_structural_posture is called with fx_rows=[]. No FX leg is ingested.",
    },
  },
  data_freshness: [
    {
      id: "FRED",
      last_as_of: "2026-05-17T00:00:00Z",
      stale_seconds: 60,
      status: "ok",
    },
  ],
  // Always [] in production: reports/gold_posture.py builds it as a literal empty list
  // and never appends. The panel that read it is deleted; the field stays for contract
  // stability, so the fixture holds what the producer actually produces.
  decomposition_rows: [],
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
  // REWRITTEN 2026-08-29 to the board's own t5 panel set.
  //
  // Two regions this used to require are deliberately gone, and neither is a loss of
  // information:
  //
  //  - the KPI STRIP. The board's t5 has none, and three of its five tiles said with less
  //    context what the gauge and three-lens panels now say with more. The two that were
  //    not otherwise stated — spot and feed health — became masthead chips, which is the
  //    board's own idiom for a fact the tab is read AGAINST rather than one it is about.
  //  - LENS 3 as its own region. The board folds valuation into "Three lenses", where its
  //    percentile anchors are the meters; its published narrative rides there too, so the
  //    engine's own sentence is not dropped along with the panel.
  it("renders every board panel as a discrete region", () => {
    render(<GoldCompassLayout state={FIXTURE} />);
    for (const name of [
      /transmission gauge/i,
      /three lenses/i,
      /anchor decay/i,
      /expression cost/i,
      // Lens 1 is TWO panels, not one. The board separates official-sector accumulation
      // from western institutional flow because they are different behaviours with
      // different reads; the merged panel promoted the strategic bucket to a headline and
      // rode the other two in a sub-line.
      /central banks/i,
      /western institutional flows/i,
      /cyclical readings/i,
      // The manifest is a panel, not a footer: one that named only the inputs it managed
      // to read presented a partial audit trail as a complete one.
      /input manifest/i,
    ]) {
      expect(screen.getByRole("region", { name })).toBeTruthy();
    }
  });

  it("follows the board's own t5 order", () => {
    // The conformance audit found this tab content-complete and wrongly framed: the
    // gauge decides whether the cyclical lens means anything, and it was one tile in a
    // five-tile strip. The board opens the tab on it, so document order is the assertion.
    const { container } = render(<GoldCompassLayout state={FIXTURE} />);
    const labels = [...container.querySelectorAll("[role='region']")].map(
      (el) => el.getAttribute("aria-label"),
    );
    const at = (re: RegExp) => labels.findIndex((l) => l && re.test(l));

    expect(at(/transmission gauge/i)).toBe(0);
    // The gauge sits BESIDE the lenses it governs, which is the argument for the pairing.
    expect(at(/three lenses/i)).toBe(1);
    expect(at(/expression cost/i)).toBeGreaterThan(at(/anchor decay/i));
    // The board's own t5 order puts central banks before the western flows they are
    // routinely conflated with.
    expect(at(/western institutional flows/i)).toBeGreaterThan(
      at(/central banks/i),
    );
    // The manifest closes the tab: an audit trail is read after what it audits.
    expect(at(/input manifest/i)).toBe(labels.length - 1);
  });

  it("gives every gold panel a board question", () => {
    // The board's acceptance test: "every panel must answer at least one, or it gets
    // deleted". `BoardPanel` makes it a type error to omit; this is the render-side check
    // that nothing reaches the page around it.
    const { container } = render(<GoldCompassLayout state={FIXTURE} />);
    const panels = [...container.querySelectorAll("[role='region']")];
    expect(panels.length).toBeGreaterThan(0);
    for (const panel of panels) {
      expect(panel.getAttribute("data-questions")).toMatch(
        /^Q[1-7]( Q[1-7])*$/,
      );
    }
  });

  it("reads the gauge as a term structure rather than a level", () => {
    // The fixture's four windows sit within 0.27 of each other, so this is the
    // agreement branch. A hardcoded "collapsed" sentence would be wrong here, which is
    // the point: the read is derived from the numbers, never restated from the board.
    render(<GoldCompassLayout state={FIXTURE} />);
    const read = screen.getByTestId("gold-gauge-read").textContent ?? "";
    expect(read).toMatch(/agree to within/i);
    expect(read).not.toMatch(/collapsed/i);
    // The regime still governs the page, and says so.
    expect(read).toMatch(/informative only/i);
  });

  it("says 'collapsed' when the near and wide windows actually diverge", () => {
    const collapsing: State = {
      ...FIXTURE,
      gauge: { ...FIXTURE.gauge, corr_60d: "-0.85", corr_504d: "-0.02" },
    };
    render(<GoldCompassLayout state={collapsing} />);
    expect(screen.getByTestId("gold-gauge-read").textContent).toMatch(
      /collapsed on the 504D/i,
    );
  });

  it("prints the skew at two decimals, not at storage precision", () => {
    // It rendered `-0.0700630226186208σ` in production: a full-precision decimal string
    // interpolated against a sigma suffix, claiming sixteen figures of measurement.
    const precise: State = {
      ...FIXTURE,
      structural: {
        ...FIXTURE.structural,
        uw_25d_skew_sigma: "-0.0700630226186208",
      },
    };
    render(<GoldCompassLayout state={precise} />);
    const panel = screen.getByRole("region", { name: /expression cost/i });
    expect(panel.textContent).toContain("-0.07\u03c3");
    expect(panel.textContent).not.toContain("0700630226186208");
  });

  it("names the correlation window it has, and the one the board asked for", () => {
    // The producer computes the history at window=252 only. Silently showing it under a
    // heading the board wrote for a 60-day series would be the wrong kind of fidelity.
    render(<GoldCompassLayout state={FIXTURE} />);
    expect(
      screen.getByTestId("correlation-history-window-note").textContent,
    ).toMatch(/60-day correlation/i);
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

  it("gives each central-bank bucket its own labelled figure", () => {
    render(<GoldCompassLayout state={FIXTURE} />);
    const cb = screen.getByRole("region", { name: /central banks/i });
    // Three buckets at equal weight. The previous layout printed the strategic figure as
    // the headline and ran all three together in a sub-line, which answered the
    // comparison the panel exists to let the reader make.
    expect(cb.textContent).toMatch(/Strategic accumulators/i);
    expect(cb.textContent).toMatch(/Tactical defenders/i);
    expect(cb.textContent).toMatch(/Reserve diversifiers/i);
    expect(cb.textContent).toContain("+210.0t");
    expect(cb.textContent).toContain("+12.0t");
    expect(cb.textContent).toContain("+34.0t");
  });

  it("derives the bucket read from the signs present, never from the board's", () => {
    // The board's own sentence says the strategic bucket was a net SELLER and the
    // diversifiers did the buying. That was true at its capture instant and inverts on
    // any WGC release, so the sentence is built from the signs actually present. The
    // fixture has all three positive; the read must not claim a seller.
    render(<GoldCompassLayout state={FIXTURE} />);
    const read = screen.getByTestId("cb-bucket-read").textContent ?? "";
    expect(read).toMatch(/needs\s+unbundling/i);
    expect(read).not.toMatch(/net sellers/i);
    expect(read).toMatch(/strategic accumulators/i);
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
    // Page starts with no CBs pre-selected — toggle should be unchecked.
    expect((chinaToggle as HTMLInputElement).checked).toBe(false);
    fireEvent.click(chinaToggle);
    expect((chinaToggle as HTMLInputElement).checked).toBe(true);
  });

  it("carries its own date picker on the standalone page, and drops it on the desk", () => {
    // `/gold/replay/<date>` has no other control, so the header's picker is the only way
    // to move. The macro desk's gold tab sits under `ReplayControl` — the desk's one
    // control, labelled with tab 05's declared `obs_date` clock — and this picker
    // navigates OFF the desk, so leaving it on would put two questions over one answer.
    const standalone = render(<GoldCompassLayout state={FIXTURE} />);
    expect(standalone.getByLabelText("REPLAY")).toBeTruthy();
    standalone.unmount();

    const onDesk = render(
      <GoldCompassLayout
        state={FIXTURE}
        showReplayPicker={false}
        deskHeading={<h2>Gold</h2>}
      />,
    );
    expect(onDesk.queryByLabelText("REPLAY")).toBeNull();
    // ...and the rest of the cockpit is untouched by the suppression.
    expect(onDesk.getByRole("region", { name: /central banks/i })).toBeTruthy();
  });

  it("wears the Gold Compass lockup standalone and the board's heading on the desk", () => {
    // Two chromes, one body — and the wordmark is the half that must not appear twice.
    // On the desk it said the same word as the tab bar one line above it, so tab 05 opens
    // with the board's `.sec-title` instead; on `/gold/replay/<date>` there is no tab bar
    // to say it, so the lockup stays.
    const standalone = render(<GoldCompassLayout state={FIXTURE} />);
    expect(
      standalone.getByRole("heading", { name: /GOLD COMPASS/i }),
    ).toBeTruthy();
    standalone.unmount();

    const onDesk = render(
      <GoldCompassLayout
        state={FIXTURE}
        showReplayPicker={false}
        deskHeading={<h2>Gold</h2>}
      />,
    );
    expect(onDesk.queryByRole("heading", { name: /GOLD COMPASS/i })).toBeNull();
    expect(onDesk.getByRole("heading", { name: "Gold" })).toBeTruthy();
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
