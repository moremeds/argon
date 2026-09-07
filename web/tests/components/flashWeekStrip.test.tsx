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

const RUNS = [row("premarket", HEADLINE), row("intraday"), row("close")];

describe("WeekStrip", () => {
  it("renders five weekdays plus the weekly card", () => {
    render(<WeekStrip weekKey="2026-W36" runs={RUNS} weeks={[WEEK_36]} />);

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

  /**
   * A day card conflated the same two facts the weekly card did: a premarket
   * run that was recorded with an empty `headline` printed "no premarket run"
   * over a run that exists. Existence is the pip; the headline is the text.
   */
  it("says `no headline recorded` for a headline-less premarket run", () => {
    render(
      <WeekStrip
        weekKey="2026-W36"
        runs={[
          row("premarket"),
          row("close"),
          { ...row("close"), run_day: "2026-09-02" },
        ]}
        weeks={[WEEK_36]}
      />,
    );

    const thu = within(screen.getByTestId("flash-day-2026-09-03"));
    expect(thu.getByText("no headline recorded")).toBeTruthy();
    expect(thu.queryByText("no premarket run")).toBeNull();
    expect(thu.getByTestId("pip-premarket").getAttribute("data-on")).toBe(
      "true",
    );

    // A day whose only run is a close still says so — that label was right.
    const wed = within(screen.getByTestId("flash-day-2026-09-02"));
    expect(wed.getByText("no premarket run")).toBeTruthy();
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
      <WeekStrip weekKey="2026-W36" runs={RUNS} weeks={[WEEK_36, earlier]} />,
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

/**
 * The weekly card must follow the run the WEEK PAGE renders.
 *
 * Reproduces the option-wizard row of 2026-W36: the weekly landed on Sunday
 * 2026-09-06 with an empty `headline` and a five-section document. The body
 * drew the sections while the card above it read "not generated yet".
 */
describe("WeekStrip weekly card", () => {
  const weeklyRow: AgentRunIndexRow = {
    ...row("weekly"),
    run_day: "2026-09-06",
    run_id: "run-735e656b-ca40-4f50-a0d9-63cf25d1c8d2",
  };

  it("lights the weekly pip for a run filed off the Friday", () => {
    render(
      <WeekStrip
        weekKey="2026-W36"
        runs={[...RUNS, weeklyRow]}
        weeks={[WEEK_36]}
      />,
    );

    const card = within(screen.getByTestId("flash-day-weekly"));
    expect(card.getByTestId("pip-weekly").getAttribute("data-on")).toBe("true");
    expect(card.queryByText("not generated yet")).toBeNull();
  });

  it("prints the weekly headline when the run carries one", () => {
    render(
      <WeekStrip
        weekKey="2026-W36"
        runs={[...RUNS, { ...weeklyRow, headline: "Week ahead: payrolls" }]}
        weeks={[WEEK_36]}
      />,
    );

    const card = within(screen.getByTestId("flash-day-weekly"));
    expect(card.getByText("Week ahead: payrolls")).toBeTruthy();
  });

  it("still says `not generated yet` when no weekly run exists", () => {
    render(<WeekStrip weekKey="2026-W36" runs={RUNS} weeks={[WEEK_36]} />);

    const card = within(screen.getByTestId("flash-day-weekly"));
    expect(card.getByText("not generated yet")).toBeTruthy();
    expect(card.getByTestId("pip-weekly").getAttribute("data-on")).toBe(
      "false",
    );
  });
});
