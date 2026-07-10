import { describe, expect, it } from "vitest";
import { anchoredVwap } from "@/lib/vwap";

// Same arithmetic verification vector as the Python test — the two impls
// must agree (server is the record of truth; client is the instant redraw).
const rows = [
  { as_of: "2026-07-06", high: 10, low: 8, close: 9, volume: 100 },
  { as_of: "2026-07-07", high: 12, low: 10, close: 11, volume: 300 },
  { as_of: "2026-07-08", high: 13, low: 11, close: 12, volume: null },
];

describe("anchoredVwap", () => {
  it("matches the server-side cumulative math incl. null-volume carry", () => {
    const pts = anchoredVwap(rows, "2026-07-06");
    expect(pts.map((p) => p.time)).toEqual([
      "2026-07-06",
      "2026-07-07",
      "2026-07-08",
    ]);
    expect(pts[0].value).toBeCloseTo(9.0, 10);
    expect(pts[1].value).toBeCloseTo(10.5, 10);
    expect(pts[2].value).toBeCloseTo(10.5, 10);
  });

  it("excludes bars before the anchor and emits nothing before first volume", () => {
    expect(anchoredVwap(rows, "2026-07-07").map((p) => p.time)).toEqual([
      "2026-07-07",
      "2026-07-08",
    ]);
    expect(anchoredVwap(rows, "2026-07-09")).toEqual([]);
    expect(anchoredVwap([], "2026-07-06")).toEqual([]);
  });
});
