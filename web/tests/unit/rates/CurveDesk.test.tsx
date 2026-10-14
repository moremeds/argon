import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CurveDesk } from "@/components/rates/CurveDesk";
import { GOLD_FACTOR } from "../../fixtures/goldFactor";
import {
  POLICY_RATES_STATE,
  SNAPSHOT,
  SNAPSHOT_PROD_2026_10_09,
  TENORS,
} from "./fixture";

/**
 * Macro desk tab 02. The market half of the old `/rates` page: the traded curve, what
 * moved it, positioning, cross-market — and the quarantined legacy rule score, which is
 * the one composite the desk still shows and the only one it names as such.
 */
describe("CurveDesk", () => {
  it("matches the artifact's nine-panel inventory and order", () => {
    const { container } = render(<CurveDesk snapshot={SNAPSHOT} />);
    expect(
      [...container.querySelectorAll(".panel > .panel-h h3")].map(
        (node) => node.textContent,
      ),
    ).toEqual([
      "Yield curve",
      "10Y decomposition",
      "Model decomposition",
      "Move drivers",
      "Supply",
      "10Y futures positioning",
      "Funding",
      "Auction demand",
      "Limits",
    ]);
  });

  it("separates what the Treasury issued from whether anyone bought it", () => {
    // Moved from `FedDesk.test.tsx` on 2026-08-28, then split on 2026-08-29. The board
    // gives tab 02 a `Supply SUB-STATE` panel AND an `Auction demand` panel because they
    // answer different questions: how much paper is coming, and whether it was absorbed.
    // Under one heading a strong bid-to-cover and a heavy calendar read as one fact about
    // supply, and they frequently point opposite ways.
    render(<CurveDesk snapshot={SNAPSHOT} />);

    const supplySection = screen.getByRole("region", {
      name: /^supply$/i,
    });
    expect(within(supplySection).getByText("Public debt")).toBeTruthy();
    expect(within(supplySection).getByText("$31.37T")).toBeTruthy();
    expect(within(supplySection).queryByText("Recent auctions")).toBeNull();

    const auctions = screen.getByRole("region", { name: /auction demand/i });
    expect(within(auctions).getByText("Recent auctions")).toBeTruthy();
    expect(within(auctions).getByText("30-Year Bond")).toBeTruthy();
    expect(within(auctions).getByText("$25.0bn")).toBeTruthy();
    expect(within(auctions).getByText("2.30")).toBeTruthy();
    expect(screen.queryByText(/Treasury auction feed not wired/)).toBeNull();
  });

  it("renders the engine's sub-state verdict beside the readings it stands on", () => {
    // The snapshot carries supply/positioning/funding as READINGS; the engine's verdict
    // on each lives on `/api/macro/rates` and this tab never fetched it. Showing the
    // readings alone makes the reader do the engine's job.
    render(
      <CurveDesk
        snapshot={SNAPSHOT}
        subStates={[
          {
            role: "plumbing",
            state: "AMPLE",
            direction: "FALLING",
            confidence: "1",
            series_ids: ["EFFR", "RRPONTSYD", "SOFR"],
            latest_period_end: "2026-08-19",
            unavailable_reason: null,
            velocity: [
              {
                metric: "sofr_effr_spread_change_13w",
                value: "7.00",
                unit: "basis_points",
                window_months: 3,
                unavailable_reason: null,
              },
            ],
            confidence_reasons: [],
          },
        ]}
      />,
    );

    // Funding is the board's name for what the engine calls `plumbing` — the same thing
    // under two vocabularies, and the desk answers to the operator.
    const funding = screen.getByRole("region", { name: /^funding$/i });
    expect(funding.textContent).toContain("Ample · Falling");
    expect(funding.textContent).toContain("+7bp");
    expect(funding.textContent).toContain("EFFR");
  });

  it("still renders a sub-state's readings when the engine published no verdict", () => {
    // The readings are facts about the tape and do not stop being true because the state
    // engine is down. A panel that vanished with its verdict would lose both.
    render(<CurveDesk snapshot={SNAPSHOT} subStates={[]} />);

    const supplySection = screen.getByRole("region", {
      name: /^supply$/i,
    });
    expect(within(supplySection).getByText("$31.37T")).toBeTruthy();
    // No verdict to show, so no verdict is claimed.
    expect(supplySection.textContent).not.toContain("IN_RANGE");
  });

  it("uses the artifact heading and panel anchors without an extra jump-nav", () => {
    render(<CurveDesk snapshot={SNAPSHOT} />);

    const sectionIds = new Set(
      Array.from(document.querySelectorAll('[role="region"][id]')).map(
        (n) => n.id,
      ),
    );
    for (const anchor of [
      "curve",
      "decomp",
      "decomp-cleveland",
      "decomp-attribution",
      "substate-supply",
      "substate-positioning",
      "substate-plumbing",
      "auctions",
      "refuses",
    ]) {
      expect(sectionIds.has(anchor)).toBe(true);
    }

    expect(screen.queryAllByRole("link")).toHaveLength(0);

    // The board's t2 heading. `/rates` 308s here, which used to be the argument for
    // keeping the old "US Rates Factor Desk" lockup; the board opens t2 with `Rates ·
    // Curve` and nothing above it, and the old name survives on `DeskEmptyState`, which
    // is what an inbound link actually reaches when there is no snapshot.
    expect(
      screen.getByRole("heading", { name: "Rates", level: 2 }),
    ).toBeTruthy();
    expect(screen.queryByText("Treasury Factor Board")).toBeNull();
    // No state pill on this tab — the board gives t2 none, because the policy/rates
    // state belongs to, and is already shown on, tab 01.
    expect(screen.queryByTestId("rates-desk-state-pill")).toBeNull();
    expect(screen.queryByText(/Snapshot update/)).toBeNull();

    for (const label of ["2Y", "5Y", "10Y", "30Y", "2s10s", "5s30s"]) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
  });

  it("renders the full eleven-tenor curve table", () => {
    render(<CurveDesk snapshot={SNAPSHOT} />);

    const curveSection = screen.getByRole("region", { name: /yield curve/i });
    for (const tenor of TENORS) {
      expect(
        within(curveSection).getByRole("row", {
          name: new RegExp(`^${tenor}\\b`),
        }),
      ).toBeTruthy();
    }
  });

  it("renders current, one-week, and one-month curve overlays from live deltas", () => {
    render(<CurveDesk snapshot={SNAPSHOT} />);

    expect(screen.getByText("PAR yield curve overlay")).toBeTruthy();
    expect(screen.getByText("Current")).toBeTruthy();
    expect(screen.getByText("1W ago")).toBeTruthy();
    expect(screen.getByText("1M ago")).toBeTruthy();
  });

  it("colors curve-table deltas by sign without a duplicate KPI strip", () => {
    render(<CurveDesk snapshot={SNAPSHOT} />);

    expect(screen.getAllByText("-5.0 bps")[0].className).toContain(
      "deltaNegative",
    );
    expect(screen.getAllByText("+5.0 bps")[0].className).toContain(
      "deltaPositive",
    );
    expect(screen.queryByText("-2.0 bps 1D")).toBeNull();
  });

  it("renders deterministic rule interpretations for slope cards", () => {
    render(<CurveDesk snapshot={SNAPSHOT} />);

    expect(screen.getByText("3m10y")).toBeTruthy();
    expect(screen.getByText(/the bills-to-10Y spread is wide/)).toBeTruthy();
    expect(screen.getByText(/Belly is rich versus wings/)).toBeTruthy();
  });

  it("never describes a curve slope as a term premium", () => {
    // A slope is a difference between two traded yields. Term premium is a model
    // output, and the only one on this page belongs to the Cleveland Fed section.
    const { container } = render(<CurveDesk snapshot={SNAPSHOT} />);
    const slopeCards = container.querySelectorAll('[data-testid="slope-card"]');
    const slopeText = Array.from(slopeCards)
      .map((node) => node.textContent ?? "")
      .join(" ");
    expect(slopeText.toLowerCase()).not.toContain("term premium");
  });

  it("renders a live decomposition dashboard with attribution rows", () => {
    render(<CurveDesk snapshot={SNAPSHOT} />);

    expect(screen.getByText("real · DFII10")).toBeTruthy();
    expect(screen.getByText("breakeven · T10YIE")).toBeTruthy();
    expect(screen.getByText(/reconciles to the stored nominal 10Y/)).toBeTruthy();
    expect(screen.getByText("E[short real]")).toBeTruthy();
    expect(screen.getByText("E[short inflation]")).toBeTruthy();
    expect(screen.getByText("real term")).toBeTruthy();
    expect(screen.getByText("inflation risk")).toBeTruthy();
    expect(screen.getByText("FRED gap")).toBeTruthy();
    expect(screen.getByText(/gap to the live daily 10Y yield/)).toBeTruthy();
    expect(screen.getAllByText("+15.3").length).toBeGreaterThan(0);
    expect(screen.getAllByText("+19.7").length).toBeGreaterThan(0);
    expect(
      screen.getByText(
        /daily market pricing has moved faster than the monthly model/,
      ),
    ).toBeTruthy();
  });

  it("renders persisted CFTC TFF positioning detail", () => {
    render(<CurveDesk snapshot={SNAPSHOT} />);

    const positioningSection = screen.getByRole("region", {
      name: /positioning/i,
    });
    expect(within(positioningSection).getByText("Asset Mgr net %OI")).toBeTruthy();
    expect(within(positioningSection).getByText("Dealer net %OI")).toBeTruthy();
    expect(within(positioningSection).getByText("Lev Money net %OI")).toBeTruthy();
    expect(positioningSection.textContent).toContain("UST 10Y NOTE");
    expect(within(positioningSection).getByText("-26.3%")).toBeTruthy();
    expect(
      within(positioningSection).getByText(/CFTC TFF 2026-05-22/),
    ).toBeTruthy();
    expect(screen.queryByText(/CFTC\/TIC feeds not wired/)).toBeNull();
  });

  it("does not add a standalone source-freshness panel absent from the artifact", () => {
    render(<CurveDesk snapshot={SNAPSHOT} />);
    expect(screen.queryByRole("region", { name: /source freshness/i })).toBeNull();
  });

  it("dashes the five model columns when a window saw no new monthly vintage", () => {
    // Prod as of 2026-10-09: 1D/1W/1M read the same 2026-09-01 Cleveland vintage at
    // both ends, so every model delta is a stored value minus itself — an exact 0.0.
    // Printing it would read as "the model explains nothing"; the table prints an
    // em dash and says why on hover instead.
    render(<CurveDesk snapshot={SNAPSHOT_PROD_2026_10_09} />);

    const drivers = screen.getByRole("region", { name: /move drivers/i });
    for (const [window, nominal] of [
      ["1D", "+2.0"],
      ["1W", "-4.0"],
      ["1M", "+41.0"],
    ] as const) {
      const cells = within(
        within(drivers).getByRole("row", { name: new RegExp(`^${window}\\b`) }),
      ).getAllByRole("cell");
      // cells: window, 10Y, Model, E[real], E[infl], Real term, Infl risk, Residual, Driver
      expect(cells[1].textContent).toBe(nominal);
      for (const cell of cells.slice(2, 7)) {
        expect(cell.textContent).toBe("—");
        expect(cell.title).toBe("no new monthly model value in this window");
      }
      // Residual and driver stay — tape minus a static model is still real.
      expect(cells[8].textContent).toBe("Real rate");
    }
    // YTD crosses a vintage boundary, so its model columns are real numbers.
    const ytd = within(
      within(drivers).getByRole("row", { name: /^YTD\b/ }),
    ).getAllByRole("cell");
    expect(ytd[2].textContent).toBe("+83.0");
  });

  it("keeps the numeric model columns when the vintage changed or the flag is absent", () => {
    // `SNAPSHOT` has no `model_vintage_changed` (older API response): every cell
    // prints as before, and the 1M read still names a model number.
    render(<CurveDesk snapshot={SNAPSHOT} />);

    const drivers = screen.getByRole("region", { name: /move drivers/i });
    const oneM = within(
      within(drivers).getByRole("row", { name: /^1M\b/ }),
    ).getAllByRole("cell");
    expect(oneM[2].textContent).toBe("+15.3");
    expect(drivers.textContent).toContain("the Cleveland model accounts for");
  });

  it("says the window has no new monthly model value instead of claiming +0.0", () => {
    render(<CurveDesk snapshot={SNAPSHOT_PROD_2026_10_09} />);

    const drivers = screen.getByRole("region", { name: /move drivers/i });
    expect(drivers.textContent).toContain("+41.0 bps");
    expect(drivers.textContent).toContain("no new monthly model value");
    expect(drivers.textContent).toContain("2026-09-01");
    expect(drivers.textContent).not.toContain("model accounts for");
  });

  it("shows gold's real-yield sensitivity beside the decompositions when the factor is live", () => {
    render(<CurveDesk snapshot={SNAPSHOT} goldFactor={GOLD_FACTOR} />);

    const panel = screen.getByRole("region", { name: /real-yield sensitivity/i });
    // Prod around 2026-10-13 read roughly −0.05 %/bp with the interval crossing zero.
    expect(panel.textContent).toContain("−0.050");
    expect(panel.textContent).toContain("interval crosses zero");
    expect(panel.textContent).toContain("through 2026-09-30");
    expect(panel.textContent).toContain("Describes the past, not a forecast");
    // Beside the model decomposition — same grid, not a separate band.
    const cleveland = screen.getByRole("region", {
      name: /model decomposition/i,
    });
    expect(panel.parentElement).toBe(cleveland.parentElement);
  });

  it("hides the gold sensitivity when no factor was fetched — replay or outage", () => {
    render(<CurveDesk snapshot={SNAPSHOT} />);

    expect(
      screen.queryByRole("region", { name: /sensitivity/i }),
    ).toBeNull();
  });

  it("hides the gold sensitivity when the latest fit lacks the real-yield row", () => {
    const factor = {
      ...GOLD_FACTOR,
      points: GOLD_FACTOR.points.map((point, index) =>
        index === GOLD_FACTOR.points.length - 1
          ? { ...point, b_r: null, b_r_lo95: null, b_r_hi95: null }
          : point,
      ),
    };
    render(<CurveDesk snapshot={SNAPSHOT} goldFactor={factor} />);

    expect(
      screen.queryByRole("region", { name: /sensitivity/i }),
    ).toBeNull();
  });

  it("prints each yield series' data date and first-stored time in New York", () => {
    render(<CurveDesk snapshot={SNAPSHOT_PROD_2026_10_09} />);

    const table = screen.getByTestId("data-dates");
    // Header + eleven curve series + DFII10 + T10YIE.
    expect(within(table).getAllByRole("row")).toHaveLength(14);

    // H.15 rows for Friday 2026-10-09 were first stored Monday 2026-10-12 at 18:45 ET.
    // (The fixture names the 10Y point DGS10Y; prod calls it DGS10.)
    const dgs10 = within(table).getByRole("row", {
      name: /DGS10Y · 10Y Treasury nominal/,
    });
    expect(dgs10.textContent).toContain("2026-10-09");
    expect(dgs10.textContent).toContain("2026-10-12 18:45 ET");

    // T10YIE is stored on the observation day itself.
    const t10yie = within(table).getByRole("row", { name: /T10YIE/ });
    expect(t10yie.textContent).toContain("2026-10-09 18:45 ET");

    // The caption states what the column is and what the warehouse cannot say.
    expect(table.textContent).toContain(
      "FRED's own publish time is not stored",
    );
  });

  it("renders an explicit empty state when no snapshot exists", () => {
    render(<CurveDesk snapshot={null} />);

    expect(screen.getByText(/Rates snapshot not computed/)).toBeTruthy();
  });

  it("renders an explicit API outage state separately from a missing snapshot", () => {
    render(
      <CurveDesk snapshot={null} errorMessage="The rates API request failed" />,
    );

    expect(screen.getByText(/Rates API unavailable/)).toBeTruthy();
    expect(screen.getByText(/The rates API request failed/)).toBeTruthy();
  });

  describe("the §7 settlement", () => {
    const withState = { ...SNAPSHOT, state: POLICY_RATES_STATE };

    it("quarantines the legacy composite inside the refusal section, still banner-labelled", () => {
      render(<CurveDesk snapshot={withState} />);

      const refusal = screen.getByRole("region", {
        name: /limits/i,
      });
      // Present, not deleted: it is the only thing an operator can hold the new state
      // up against. But it lives INSIDE the refusal that names it a legacy artifact.
      const scorecard = within(refusal).getByTestId("rates-scorecard");
      expect(scorecard).toBeTruthy();
      expect(
        within(scorecard).getByTestId("scorecard-legacy-banner").textContent,
      ).toMatch(/experimental legacy/i);
      // The refusal states it in prose BEFORE the number appears.
      expect(refusal.textContent).toMatch(/slope is not a term premium/i);
      expect(refusal.textContent).toMatch(/Daily market data stays separate/i);
      expect(refusal.textContent).toMatch(/Experimental legacy scorecard/i);
      // Every testid the e2e spec pins survives the move.
      expect(within(refusal).getByTestId("duration-score")).toBeTruthy();
      expect(within(refusal).getByTestId("duration-stance")).toBeTruthy();
    });

    it("puts the refusal after everything the tab does answer", () => {
      const { container } = render(<CurveDesk snapshot={withState} />);

      const ids = Array.from(
        container.querySelectorAll('[role="region"][id]'),
      ).map((node) => node.id);
      expect(ids[0]).toBe("curve");
      expect(ids.indexOf("refuses")).toBeGreaterThan(ids.indexOf("curve"));
      expect(ids.indexOf("refuses")).toBeGreaterThan(ids.indexOf("decomp"));
      expect(ids.indexOf("refuses")).toBeGreaterThan(
        ids.indexOf("substate-positioning"),
      );
      expect(ids[ids.length - 1]).toBe("refuses");
    });

    it("prescribes nothing: no stance card, no BUY/SELL anywhere in the tab", () => {
      const { container } = render(<CurveDesk snapshot={withState} />);

      expect(screen.queryByTestId("legacy-stance-grid")).toBeNull();
      expect(screen.queryByText("Duration stance")).toBeNull();
      expect(screen.queryByText("Curve stance")).toBeNull();
      expect(container.textContent ?? "").not.toMatch(/\b(BUY|SELL)\b/);
    });

    it("does not narrate the composite: the synthesis prose is gone", () => {
      const { container } = render(<CurveDesk snapshot={withState} />);

      const text = container.textContent ?? "";
      expect(text).not.toContain(SNAPSHOT.synthesis.duration_view);
      expect(text).not.toContain(SNAPSHOT.synthesis.curve_view);
      for (const risk of SNAPSHOT.synthesis.risks ?? []) {
        expect(text).not.toContain(risk);
      }
      expect(screen.queryByRole("region", { name: /synthesis/i })).toBeNull();
    });
  });
});
