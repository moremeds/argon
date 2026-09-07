import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { WeeklyView } from "@/components/flash/WeeklyView";
import type { AgentRunIndexRow, AgentRunResponse } from "@/lib/api";

import WEEKLY_V3 from "../fixtures/heliumBriefViewV3Weekly.json";

/** The recorded option-wizard weekly run of 2026-09-06, verbatim. */
const WEEKLY_RUN = {
  run_day: "2026-09-06",
  kind: "weekly",
  run_id: "run-bf4b1795-b627-4df8-a5fe-b744ffb8e0d1",
  version_no: 1,
  outcome: "completed",
  headline: "",
  code_sha: "abc1234",
  schema_version: 3,
  created_at: "2026-09-06T21:27:00Z",
  tenant: "option-wizard",
  view: WEEKLY_V3,
} as unknown as AgentRunResponse;

const row = (kind: string): AgentRunIndexRow => ({
  run_day: "2026-09-03",
  kind,
  run_id: `run-${kind}`,
  version_no: 1,
  outcome: "ok",
  headline:
    kind === "premarket"
      ? "Real yields did the work — DFII10 ran +12bp to 2.44%."
      : "",
  code_sha: "abc1234",
  schema_version: 1,
  created_at: "2026-09-03T17:01:15Z",
});

const RUNS = [row("premarket"), row("intraday"), row("close")];

describe("WeeklyView", () => {
  it("renders one row per weekday with its run count", () => {
    render(
      <WeeklyView weekKey="2026-W36" runs={RUNS} weekly={null} frank={null} />,
    );
    const rows = screen.getAllByTestId(/^weekly-row-/);
    expect(rows).toHaveLength(5);
    expect(screen.getByTestId("weekly-row-2026-09-03").textContent).toContain(
      "3 runs",
    );
    expect(screen.getByTestId("weekly-row-2026-08-31").textContent).toContain(
      "0 runs",
    );
    expect(screen.getByTestId("weekly-row-2026-08-31").textContent).toContain(
      "no run recorded",
    );
  });

  it("carries the premarket one-liner into the recorded day's row", () => {
    render(
      <WeeklyView weekKey="2026-W36" runs={RUNS} weekly={null} frank={null} />,
    );
    expect(screen.getByText(/Real yields did the work/)).toBeTruthy();
  });

  it("says the outlook is generated Sunday morning, not Friday after close", () => {
    const { container } = render(
      <WeeklyView weekKey="2026-W36" runs={RUNS} weekly={null} frank={null} />,
    );
    expect(screen.getByText("Generated Sunday morning")).toBeTruthy();
    expect(container.textContent).not.toContain("Friday after close");
  });

  it("preserves recorded v3 blocks without an empty Frank column", () => {
    render(
      <WeeklyView
        weekKey="2026-W36"
        runs={RUNS}
        weekly={WEEKLY_RUN}
        frank={null}
      />,
    );
    expect(screen.getByText("1 · Scorecard")).toBeTruthy();
    expect(screen.getByText("Focus")).toBeTruthy();
    expect(screen.getByText("Themes")).toBeTruthy();
    expect(screen.getByText("Rotation")).toBeTruthy();
    expect(screen.getByText("Sources & as-of")).toBeTruthy();
    expect(screen.getByText("Run health")).toBeTruthy();
    // the version band the page used to show for a v3 run
    expect(screen.queryByText(/Unrenderable version/)).toBeNull();
    expect(screen.queryByText("Frank 复盘")).toBeNull();
  });

  it("omits the Frank slot when no external supplement exists", () => {
    render(
      <WeeklyView weekKey="2026-W36" runs={RUNS} weekly={null} frank={null} />,
    );
    expect(screen.queryByText("Frank 复盘")).toBeNull();
    expect(screen.queryByText("No review attached")).toBeNull();
  });
  it("puts the market article before the day index and keeps internal sections private", () => {
    const weekly = {
      ...WEEKLY_RUN,
      view: {
        ...WEEKLY_V3,
        headline: "Rates reset the week",
        sections: [{ title: "Market review", body: "Market thesis sentinel." }],
        otherSections: [{ title: "Internal", body: "PRIVATE SCORE SENTINEL" }],
      },
    } as unknown as AgentRunResponse;
    const frank = {
      ...weekly,
      view: {
        ...WEEKLY_V3,
        sections: [
          {
            title: "External perspective",
            body: "Frank perspective sentinel.",
          },
        ],
      },
    } as unknown as AgentRunResponse;
    const { container } = render(
      <WeeklyView
        weekKey="2026-W36"
        runs={RUNS}
        weekly={weekly}
        frank={frank}
      />,
    );
    const text = container.textContent ?? "";
    expect(text.indexOf("Rates reset the week")).toBeLessThan(
      text.indexOf("Market thesis sentinel"),
    );
    expect(text.indexOf("Market thesis sentinel")).toBeLessThan(
      text.indexOf("The week, one line a day"),
    );
    expect(text.indexOf("Market thesis sentinel")).toBeLessThan(
      text.indexOf("Frank perspective sentinel"),
    );
    expect(text).not.toContain("PRIVATE SCORE SENTINEL");
  });
  it("shows a repeated lead once and keeps raw supporting coverage collapsed", () => {
    const weekly = {
      ...WEEKLY_RUN,
      view: {
        ...WEEKLY_V3,
        headline: "Unique market conclusion.",
        sections: [
          {
            title: "Market review",
            body: "Unique market conclusion. Main news remains visible.",
          },
          { title: "Outlook", body: "Next week's conditions." },
          {
            title: "Supporting coverage",
            body: "Complete raw coverage sentinel.",
          },
        ],
      },
    } as unknown as AgentRunResponse;
    const { container } = render(
      <WeeklyView weekKey="2026-W36" runs={[]} weekly={weekly} frank={null} />,
    );
    expect(
      container.textContent?.match(/Unique market conclusion/g),
    ).toHaveLength(1);
    expect(
      screen.getByText(/Main news remains visible/).closest("details"),
    ).toBeNull();
    const appendix = screen
      .getByText("Complete raw coverage sentinel.")
      .closest("details");
    expect(appendix).not.toBeNull();
    expect(appendix?.open).toBe(false);
    expect(appendix?.querySelector("summary")?.textContent).toBe(
      "Supporting coverage",
    );
    expect(
      screen.getByText("Next week's conditions.").closest("details"),
    ).toBeNull();
  });
});
