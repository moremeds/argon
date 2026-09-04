import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { WeekStrip } from "@/components/flash/WeekStrip";
import type { AgentRunIndexRow, AgentRunWeek } from "@/lib/api";

/**
 * The recorded week of 2026-08-31 → 2026-09-04: one day (Thursday) carries all
 * three phases, the other four carry nothing. Every string below is from the
 * captured option-wizard run, not invented.
 */
const HEADLINE =
  "Real yields did the work — DFII10 ran +12bp to 2.44% while VIX broke its " +
  "August 14-handle pin to 16.34 into tomorrow's payroll.";

function row(kind: string, headline = ""): AgentRunIndexRow {
  return {
    run_day: "2026-09-03",
    kind,
    run_id: `ow-${kind}-2026-09-03`,
    version_no: 1,
    outcome: "completed",
    headline,
    code_sha: "3b9fdc4c",
    schema_version: 1,
    created_at: "2026-09-03T17:01:15.101Z",
  };
}

const WEEK_36: AgentRunWeek = {
  week_key: "2026-W36",
  first_day: "2026-08-31",
  last_day: "2026-09-04",
  run_count: 3,
  day_count: 1,
};

const RUNS = [
  row("premarket", HEADLINE),
  row("intraday"),
  row("close"),
];

describe("WeekStrip", () => {
  it("renders five weekdays plus the weekly card", () => {
    render(
      <WeekStrip weekKey="2026-W36" runs={RUNS} weeks={[WEEK_36]} />,
    );

    for (const dow of ["MON", "TUE", "WED", "THU", "FRI"]) {
      expect(screen.getByText(dow)).toBeTruthy();
    }
    expect(screen.getByText("WEEK")).toBeTruthy();
    expect(screen.getByTestId("flash-day-2026-08-31")).toBeTruthy();
    expect(screen.getByTestId("flash-day-2026-09-04")).toBeTruthy();
  });

  it("lights a pip only for a kind that was actually recorded", () => {
    render(
      <WeekStrip
        weekKey="2026-W36"
        runs={[row("premarket", HEADLINE), row("close")]}
        weeks={[WEEK_36]}
      />,
    );

    const thu = within(screen.getByTestId("flash-day-2026-09-03"));
    expect(thu.getByTestId("pip-premarket").getAttribute("data-on")).toBe(
      "true",
    );
    expect(thu.getByTestId("pip-intraday").getAttribute("data-on")).toBe(
      "false",
    );
    expect(thu.getByTestId("pip-close").getAttribute("data-on")).toBe("true");

    const mon = within(screen.getByTestId("flash-day-2026-08-31"));
    expect(mon.getByTestId("pip-premarket").getAttribute("data-on")).toBe(
      "false",
    );
  });

  it("shows the premarket headline on the day that has one", () => {
    render(<WeekStrip weekKey="2026-W36" runs={RUNS} weeks={[WEEK_36]} />);

    expect(
      within(screen.getByTestId("flash-day-2026-09-03")).getByText(HEADLINE),
    ).toBeTruthy();
  });

  it("says `no run recorded` on a day that has none", () => {
    render(<WeekStrip weekKey="2026-W36" runs={RUNS} weeks={[WEEK_36]} />);

    const mon = within(screen.getByTestId("flash-day-2026-08-31"));
    expect(mon.getByText("no run recorded")).toBeTruthy();
  });

  it("marks the selected day pressed and nothing else", () => {
    render(
      <WeekStrip
        weekKey="2026-W36"
        runs={RUNS}
        weeks={[WEEK_36]}
        selectedDay="2026-09-03"
      />,
    );

    expect(
      screen.getByTestId("flash-day-2026-09-03").getAttribute("aria-pressed"),
    ).toBe("true");
    expect(
      screen.getByTestId("flash-day-2026-08-31").getAttribute("aria-pressed"),
    ).toBe("false");
  });

  it("disables both arrows when this is the only recorded week", () => {
    render(<WeekStrip weekKey="2026-W36" runs={RUNS} weeks={[WEEK_36]} />);

    const prev = screen.getByTestId("flash-week-prev");
    const next = screen.getByTestId("flash-week-next");
    expect(prev.hasAttribute("disabled")).toBe(true);
    expect(next.hasAttribute("disabled")).toBe(true);
    expect(prev.getAttribute("title")).toContain("earlier");
    expect(next.getAttribute("title")).toContain("later");
  });

  it("walks the recorded weeks, not the calendar", () => {
    const earlier: AgentRunWeek = {
      week_key: "2026-W30",
      first_day: "2026-07-20",
      last_day: "2026-07-24",
      run_count: 1,
      day_count: 1,
    };
    // The list arrives newest-first, so "earlier" is index + 1.
    render(
      <WeekStrip
        weekKey="2026-W36"
        runs={RUNS}
        weeks={[WEEK_36, earlier]}
      />,
    );

    const prev = screen.getByTestId("flash-week-prev");
    expect(prev.getAttribute("href")).toBe("/flash/2026-W30");
    expect(screen.getByTestId("flash-week-next").hasAttribute("disabled")).toBe(
      true,
    );
  });

  it("counts the days that have a run, in the mock's own words", () => {
    render(<WeekStrip weekKey="2026-W36" runs={RUNS} weeks={[WEEK_36]} />);

    expect(
      screen.getByText("W36 · 1 of 5 days has a recorded run"),
    ).toBeTruthy();
    expect(screen.getByText("2026-08-31 → 2026-09-04")).toBeTruthy();
  });
});
