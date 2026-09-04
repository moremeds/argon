import { describe, expect, it } from "vitest";

import {
  DAY_KINDS,
  FLASH_TENANT,
  KIND_LABEL,
  PIP_LABEL,
  WEEK_KINDS,
  isoWeekOf,
  weekDays,
  weekRange,
} from "@/lib/flash/kinds";

/**
 * Week arithmetic is the one piece of Flash that can be wrong without looking
 * wrong: a Monday shifted into the previous Sunday still renders five cards.
 * All of it is UTC on purpose — a trading date is a label, not an instant.
 */
describe("flash kinds", () => {
  it("names option-wizard's five kinds and nothing else", () => {
    expect(FLASH_TENANT).toBe("option-wizard");
    expect(DAY_KINDS).toEqual(["premarket", "intraday", "close"]);
    expect(WEEK_KINDS).toEqual(["weekly", "frank"]);
    expect(PIP_LABEL).toEqual({ premarket: "P", intraday: "I", close: "C" });
    expect(KIND_LABEL.premarket).toBe("Premarket");
    expect(KIND_LABEL.frank).toBe("Frank 复盘");
  });
});

describe("isoWeekOf", () => {
  it("puts the recorded 2026-09-03 run in W36", () => {
    expect(isoWeekOf("2026-09-03")).toBe("2026-W36");
    expect(isoWeekOf("2026-08-31")).toBe("2026-W36");
    expect(isoWeekOf("2026-09-04")).toBe("2026-W36");
  });

  it("uses the ISO year, which is not the calendar year at the boundary", () => {
    // 2026-12-31 is a Thursday, so its ISO week is the 53rd of 2026 — the
    // plan's example ("2027-W01") named the wrong side of the roll-over.
    expect(isoWeekOf("2026-12-31")).toBe("2026-W53");
    // 2025-12-29 is a Monday whose Thursday falls in 2026: ISO year 2026.
    expect(isoWeekOf("2025-12-29")).toBe("2026-W01");
  });

  it("zero-pads a single-digit week", () => {
    expect(isoWeekOf("2026-01-05")).toBe("2026-W02");
  });
});

describe("weekDays / weekRange", () => {
  it("gives Monday..Friday of the recorded week", () => {
    expect(weekDays("2026-W36")).toEqual([
      { date: "2026-08-31", dow: "MON" },
      { date: "2026-09-01", dow: "TUE" },
      { date: "2026-09-02", dow: "WED" },
      { date: "2026-09-03", dow: "THU" },
      { date: "2026-09-04", dow: "FRI" },
    ]);
  });

  it("ranges from the Monday to the Friday", () => {
    expect(weekRange("2026-W36")).toEqual({
      first: "2026-08-31",
      last: "2026-09-04",
    });
  });

  it("round-trips every day of the week back to its own key", () => {
    for (const { date } of weekDays("2026-W36")) {
      expect(isoWeekOf(date)).toBe("2026-W36");
    }
  });
});
