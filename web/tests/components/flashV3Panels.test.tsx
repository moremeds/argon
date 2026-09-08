import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Body } from "@/components/flash/Body";
import { EverythingElsePanel } from "@/components/flash/EverythingElsePanel";
import { FocusPanel } from "@/components/flash/FocusPanel";
import { FooterPanel } from "@/components/flash/FooterPanel";
import { OneThingPanel } from "@/components/flash/OneThingPanel";
import { RotationPanel } from "@/components/flash/RotationPanel";
import { ThemesPanel } from "@/components/flash/ThemesPanel";
import { asBriefView, type BriefView } from "@/components/flash/view";

import CLOSE_FIXTURE from "../fixtures/heliumBriefViewV3Close.json";
import WEEKLY_FIXTURE from "../fixtures/heliumBriefViewV3Weekly.json";

/**
 * The producer's own v3 output, frozen: the weekly run of 2026-09-06 and the
 * close run of 2026-09-04, both recorded by option-wizard. Every string here
 * is helium's. A panel that stops rendering the real document fails here.
 */
function viewOf(fixture: unknown): BriefView {
  const view = asBriefView({
    schema_version: 3,
    view: fixture,
    run_day: "2026-09-06",
    headline: "h",
    outcome: "completed",
    tenant: "option-wizard",
  } as never);
  if (!view) throw new Error("the frozen v3 fixture no longer parses");
  return view;
}

const WEEKLY = viewOf(WEEKLY_FIXTURE);
const CLOSE = viewOf(CLOSE_FIXTURE);

describe("FocusPanel", () => {
  it("prints every focus name in the run's own order, with its IV rank", () => {
    render(<FocusPanel focus={WEEKLY.focus!} />);
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows.length).toBe(WEEKLY.focus!.rows.length);
    expect(within(rows[0]).getByText("ADBE")).toBeTruthy();
    expect(within(rows[0]).getByText("69")).toBeTruthy();
    expect(
      within(rows[0]).getByText("2026-09-04-close-focus-ADBE"),
    ).toBeTruthy();
  });

  it("says the churn the run counted, rather than implying none", () => {
    render(<FocusPanel focus={CLOSE.focus!} />);
    expect(screen.getByText(/churn 0/)).toBeTruthy();
  });

  it("prints an em dash for a name the run gave no reason for", () => {
    const asml = CLOSE.focus!.rows.find((r) => r.ticker === "ASML")!;
    expect(asml.why).toBe("");
    render(<FocusPanel focus={{ rows: [asml] }} />);
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });
});

describe("ThemesPanel", () => {
  it("shows the token, both excess strings and the kill condition", () => {
    render(<ThemesPanel themes={WEEKLY.themes!} />);
    expect(screen.getByText("strengthen")).toBeTruthy();
    expect(screen.getByText("+6.5%")).toBeTruthy();
    expect(screen.getByText("+0.0%")).toBeTruthy();
    expect(screen.getByText("kill")).toBeTruthy();
    expect(screen.getByText(/ONI < \+0\.5 two months running/)).toBeTruthy();
  });

  it("says KILL MET only when the run said so", () => {
    expect(WEEKLY.themes![0]!.killMet).toBe(false);
    render(<ThemesPanel themes={[{ ...WEEKLY.themes![0]!, killMet: true }]} />);
    expect(screen.getByText("kill met")).toBeTruthy();
  });
});

describe("RotationPanel", () => {
  it("heads the table with the as-of the run measured against", () => {
    render(<RotationPanel rotation={WEEKLY.rotation!} />);
    expect(screen.getByText(/as of 2026-09-04/)).toBeTruthy();
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows.length).toBe(WEEKLY.rotation!.rows.length);
    expect(within(rows[0]).getByText("+6.6")).toBeTruthy();
  });

  it("prints a stale symbol as untested, never as a flat week", () => {
    const untested = {
      symbol: "XLE",
      label: "XLE",
      w1: null,
      w4: null,
      w12: null,
      excess1w: null,
      excess4w: null,
      excess12w: null,
      untested: "no bar on 2026-08-28; newest 2026-07-13",
    };
    render(<RotationPanel rotation={{ rows: [untested] }} />);
    expect(screen.getAllByText("untested").length).toBe(6);
    expect(screen.queryByText("0.0")).toBeNull();
    expect(screen.getByText(/no bar on 2026-08-28/)).toBeTruthy();
  });
});

describe("FooterPanel", () => {
  it("lists coverage, as-of and notes verbatim", () => {
    render(
      <FooterPanel footer={WEEKLY.footer!} staleness={WEEKLY.staleness} />,
    );
    expect(screen.getByText("macro — ow_macro_rates")).toBeTruthy();
    expect(screen.getByText(/ow_spot — 2026-09-06T21:26:56/)).toBeTruthy();
    expect(
      screen.getByText("bars: 50 of 50 basket symbols answered"),
    ).toBeTruthy();
  });
});

describe("OneThingPanel", () => {
  it("puts the claim, yesterday's scoring line and all three checks on the page", () => {
    render(
      <OneThingPanel
        oneThing={CLOSE.oneThing}
        checks={CLOSE.checks}
        changeMyMind={CLOSE.changeMyMind}
      />,
    );
    expect(screen.getByText("The one thing")).toBeTruthy();
    expect(screen.getByText(/no single move stood out/)).toBeTruthy();
    // the run wrote the scoring sentence into the body as well; it prints once
    expect(screen.getByText(/Yesterday: no prior checks\./)).toBeTruthy();
    expect(screen.queryAllByText("Yesterday: no prior checks.")).toHaveLength(
      0,
    );

    const checks = screen.getAllByRole("listitem");
    expect(checks).toHaveLength(3);
    expect(within(checks[0]).getByText("VIXCLS")).toBeTruthy();
    expect(within(checks[0]).getByText("at 14.32")).toBeTruthy();
    expect(
      within(checks[0]).getByText(/compression extend below 14\.25/),
    ).toBeTruthy();
  });

  it("prints the scoring line on its own when the body does not repeat it", () => {
    render(
      <OneThingPanel
        oneThing={{
          title: "The one thing",
          body: "Vol is the regime.",
          checksLine: "Yesterday: 2 of 3 checks held.",
        }}
      />,
    );
    expect(screen.getByText("Yesterday: 2 of 3 checks held.")).toBeTruthy();
  });

  it("prints the condition that would break the read, with its horizon", () => {
    render(<OneThingPanel changeMyMind={CLOSE.changeMyMind} />);
    expect(screen.getByText(/HY OAS sustained wider than 2\.65%/)).toBeTruthy();
    expect(screen.getByText("BAMLH0A0HYM2 · >2.65 · 3 sessions")).toBeTruthy();
  });

  it("draws nothing at all when the run wrote no claim", () => {
    const { container } = render(<OneThingPanel />);
    expect(container.innerHTML).toBe("");
  });
});

describe("EverythingElsePanel", () => {
  it("lists what the run left out of the argument", () => {
    render(<EverythingElsePanel items={CLOSE.everythingElse!} />);
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
    expect(screen.getByText(/USD broad index 118\.7/)).toBeTruthy();
  });
});

describe("Body coverage verdicts", () => {
  it("sets a coverage verdict apart without rewriting the line", () => {
    const coverage = WEEKLY.sections!.find((s) => s.title === "3 · Coverage")!;
    const { container } = render(<Body text={coverage.body} />);
    const chips = container.querySelectorAll("[data-cov]");
    expect(chips.length).toBeGreaterThan(5);
    expect([...chips].map((c) => c.textContent).includes("UNTESTED")).toBe(
      true,
    );
    expect(container.textContent).toContain(
      "rates.long — 4.77 → -2 bp — CONTINUE",
    );
  });
});
