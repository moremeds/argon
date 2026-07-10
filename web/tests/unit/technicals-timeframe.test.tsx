/* @vitest-environment jsdom */
import { describe, expect, it } from "vitest";
import {
  sliceSeriesByTimeframe,
  type Timeframe,
} from "@/components/stock/tabs/TechnicalsTab";

// Dates chosen so each window has a distinct, hand-checkable membership.
// Anchor (last row) is 2026-07-09.
const rows = [
  { as_of: "2025-03-01" }, // > 1y before the anchor — only 'full' keeps this
  { as_of: "2025-11-15" },
  { as_of: "2025-12-20" },
  { as_of: "2026-01-05" },
  { as_of: "2026-04-08" },
  { as_of: "2026-05-10" },
  { as_of: "2026-07-02" },
  { as_of: "2026-07-09" },
];

function dates(tf: Timeframe): string[] {
  return sliceSeriesByTimeframe(rows, tf).map((r) => r.as_of);
}

describe("sliceSeriesByTimeframe", () => {
  it("returns the whole series for 'full'", () => {
    expect(sliceSeriesByTimeframe(rows, "full")).toHaveLength(rows.length);
  });

  it("keeps rows since Jan 1 of the anchor year for 'ytd'", () => {
    expect(dates("ytd")).toEqual([
      "2026-01-05",
      "2026-04-08",
      "2026-05-10",
      "2026-07-02",
      "2026-07-09",
    ]);
  });

  it("keeps rows within 1 year of the anchor for '1y'", () => {
    // 2026-07-09 minus 1 year = 2025-07-09, so 2025-11-15 onward is kept.
    expect(dates("1y")).toEqual([
      "2025-11-15",
      "2025-12-20",
      "2026-01-05",
      "2026-04-08",
      "2026-05-10",
      "2026-07-02",
      "2026-07-09",
    ]);
  });

  it("keeps rows within 3 calendar months of the anchor for '3m'", () => {
    // 2026-07-09 minus 3 months = 2026-04-09, so 2026-04-08 is just out.
    expect(dates("3m")).toEqual(["2026-05-10", "2026-07-02", "2026-07-09"]);
  });

  it("handles year rollover in the 3m cutoff", () => {
    const feb = [
      { as_of: "2025-10-31" },
      { as_of: "2025-11-15" },
      { as_of: "2026-02-09" },
    ];
    // 2026-02-09 minus 3 months = 2025-11-09.
    expect(sliceSeriesByTimeframe(feb, "3m").map((r) => r.as_of)).toEqual([
      "2025-11-15",
      "2026-02-09",
    ]);
  });

  it("returns the input unchanged for an empty series", () => {
    expect(sliceSeriesByTimeframe([], "ytd")).toEqual([]);
  });

  it("anchors on the last DATED row when the tail row has a null as_of", () => {
    // A spliced live head with no date must not defeat the window: it still
    // slices to 3M off the last dated row (the undated tail itself drops out via
    // the cutoff filter), rather than falling back to the full series.
    const withNullHead = [...rows, { as_of: null }];
    expect(
      sliceSeriesByTimeframe(withNullHead, "3m").map((r) => r.as_of),
    ).toEqual(["2026-05-10", "2026-07-02", "2026-07-09"]);
  });
});
