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

  it("renders the v3 review blocks under the outlook, Frank column intact", () => {
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
    expect(screen.getByText("Frank 复盘")).toBeTruthy();
  });

  it("shows the Frank slot as an honest empty state", () => {
    render(
      <WeeklyView weekKey="2026-W36" runs={RUNS} weekly={null} frank={null} />,
    );
    expect(screen.getByText("Frank 复盘")).toBeTruthy();
    expect(screen.getByText("No review attached")).toBeTruthy();
  });
});
