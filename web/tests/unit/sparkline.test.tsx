import { describe, it, expect } from "vitest";
import { sparklinePath } from "@/components/watchlist/Sparkline";

describe("sparklinePath", () => {
  it("returns empty path for empty input", () => {
    expect(sparklinePath([], 100, 30)).toBe("");
  });
  it("draws a flat line for constant data", () => {
    const d = sparklinePath([10, 10, 10, 10], 100, 30);
    expect(d).toMatch(/^M0,15 L33.33,15 L66.67,15 L100,15$/);
  });
  it("scales min to bottom and max to top", () => {
    const d = sparklinePath([10, 20], 100, 30);
    expect(d).toBe("M0,30 L100,0");
  });
});
