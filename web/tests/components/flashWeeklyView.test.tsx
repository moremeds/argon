import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { WeeklyView } from "@/components/flash/WeeklyView";
import type { AgentRunIndexRow } from "@/lib/api";

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

  it("shows the Frank slot as an honest empty state", () => {
    render(
      <WeeklyView weekKey="2026-W36" runs={RUNS} weekly={null} frank={null} />,
    );
    expect(screen.getByText("Frank 复盘")).toBeTruthy();
    expect(screen.getByText("No review attached")).toBeTruthy();
  });
});
