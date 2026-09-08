import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SupplementView } from "@/components/flash/SupplementView";
import type { AgentRunIndexRow } from "@/lib/api";
import { asBriefView, type BriefView } from "@/components/flash/view";

import CLOSE_V3 from "../fixtures/heliumBriefViewV3Close.json";

/** The recorded option-wizard close run of 2026-09-04, verbatim. */
const CLOSE_V3_VIEW = asBriefView({
  schema_version: 3,
  view: CLOSE_V3,
  run_day: "2026-09-04",
  headline: "h",
  outcome: "completed",
  tenant: "option-wizard",
} as never)!;

const PREMARKET_ROW = {
  run_day: "2026-09-03",
  kind: "premarket",
  run_id: "run-9a2f",
  version_no: 1,
  outcome: "ok",
  headline: "Real yields did the work.",
  code_sha: "abc1234",
  schema_version: 1,
  created_at: "2026-09-03T17:01:15Z",
} satisfies AgentRunIndexRow;

/** The recorded intraday run of 2026-09-03, trimmed to what the view needs. */
const INTRADAY: BriefView = {
  schemaVersion: 1,
  date: "2026-09-03",
  runId: "run-5cc65a12-a112-49fb-8566-ca01dc09ecc4",
  asOf: "2026-09-03T17:00:06Z",
  headline:
    "Curve bull-steepens as 2Y sheds 3.5bp into Friday's payroll, gold rips to $4,486.",
  tape: [{ label: "SPY", value: "772.92", change: "+7.76" }],
  status: [
    {
      title: "QQQ-2026-09-03-1 — put debit 710/665",
      state: "not armed",
      body: "Entry is a break below 710 and spot is 717.57 — 7.57 above the trigger, so the spread has not armed.",
    },
  ],
  gex: [
    {
      ticker: "SPY",
      spot: "772.92",
      flip: "772.53",
      magnet: "771",
      callWall: "773",
      putWall: "768",
    },
  ],
  degradation: ["tool unconfigured: ow_ib_positions (OW_IB_API_BASE unset)"],
};

describe("SupplementView · v3", () => {
  it("opens with the claim, then its checks, then what it left out", () => {
    const { container } = render(
      <SupplementView
        view={CLOSE_V3_VIEW}
        kind="close"
        weekKey="2026-W36"
        day="2026-09-04"
        runs={[PREMARKET_ROW]}
      />,
    );
    const text = container.textContent ?? "";
    expect(text).toContain("The one thing");
    expect(text).toContain("Yesterday: no prior checks.");
    expect(text).toContain("Everything else");
    // the order IS the argument: the claim precedes the leftovers
    expect(text.indexOf("The one thing")).toBeLessThan(
      text.indexOf("Everything else"),
    );
    expect(screen.getByText("Focus")).toBeTruthy();
    expect(screen.getByText("Themes")).toBeTruthy();
    expect(screen.getByText("Sources & as-of")).toBeTruthy();
  });

  it("prints the per-item faults beside the run's degradation sentence", () => {
    const { container } = render(
      <SupplementView
        view={CLOSE_V3_VIEW}
        kind="close"
        weekKey="2026-W36"
        day="2026-09-04"
        runs={[PREMARKET_ROW]}
      />,
    );
    expect(container.textContent).toContain(
      "focus TSLA: not on the computed list",
    );
    expect(container.textContent).toContain("gate flash-budget refused");
  });
});

describe("SupplementView", () => {
  it("says it is a supplement and links back to the day's premarket report", () => {
    const { container } = render(
      <SupplementView
        view={INTRADAY}
        kind="intraday"
        weekKey="2026-W36"
        day="2026-09-03"
        runs={[PREMARKET_ROW]}
      />,
    );
    expect(container.textContent).toMatch(
      /Supplement to the premarket report of 2026-09-03/,
    );
    const link = screen.getByRole("link", { name: /premarket report/i });
    expect(link.getAttribute("href")).toBe(
      "/flash/2026-W36/2026-09-03?phase=premarket",
    );
  });

  it("stands alone, with no dead link, when no premarket run exists", () => {
    const { container } = render(
      <SupplementView
        view={INTRADAY}
        kind="intraday"
        weekKey="2026-W36"
        day="2026-09-03"
        runs={[]}
      />,
    );
    expect(container.textContent).toMatch(
      /No premarket run was recorded for this day, so this supplement stands alone\./,
    );
    expect(
      screen.queryByRole("link", { name: /premarket report/i }),
    ).toBeNull();
  });

  it("surfaces the run's own recorded faults", () => {
    const { container } = render(
      <SupplementView
        view={INTRADAY}
        kind="intraday"
        weekKey="2026-W36"
        day="2026-09-03"
        runs={[PREMARKET_ROW]}
      />,
    );
    expect(container.textContent).toContain(
      "run-5cc65a12-a112-49fb-8566-ca01dc09ecc4",
    );
    expect(
      within(container).getByText(/tool unconfigured: ow_ib_positions/),
    ).toBeTruthy();
  });

  it("renders the tracked candidate with its state pill", () => {
    render(
      <SupplementView
        view={INTRADAY}
        kind="intraday"
        weekKey="2026-W36"
        day="2026-09-03"
        runs={[PREMARKET_ROW]}
      />,
    );
    expect(screen.getByText("not armed")).toBeTruthy();
    expect(screen.getByText(/7\.57 above the trigger/)).toBeTruthy();
  });

  it("omits the gamma delta table when only one of the two runs is in hand", () => {
    const { container } = render(
      <SupplementView
        view={INTRADAY}
        kind="close"
        weekKey="2026-W36"
        day="2026-09-03"
        runs={[PREMARKET_ROW]}
      />,
    );
    expect(container.textContent).not.toContain("What changed");
  });

  it("shows the delta against the intraday run when both are in hand", () => {
    const { container } = render(
      <SupplementView
        view={{
          ...INTRADAY,
          gex: [
            {
              ticker: "SPY",
              spot: "772.66",
              flip: "778.08",
              magnet: "773",
              callWall: "773",
              putWall: "772",
            },
          ],
        }}
        kind="close"
        weekKey="2026-W36"
        day="2026-09-03"
        runs={[PREMARKET_ROW]}
        priorGex={INTRADAY.gex}
        priorAsOf="2026-09-03T17:00:06Z"
      />,
    );
    expect(container.textContent).toContain("Level shifts");
    // Spot 772.92 → 772.66 is −0.26; the sign is a real minus, not a hyphen.
    expect(container.textContent).toContain("−0.26");
  });
});
