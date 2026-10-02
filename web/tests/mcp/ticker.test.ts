// normalizeTicker — the path-traversal gate for every tool value that lands
// in an apiGet path. The probe "../%68%65%61%6c%74%68#" reached /api/health
// before this existed.
import { describe, expect, it } from "vitest";
import { normalizeTicker } from "@/mcp/lib/ticker";

describe("normalizeTicker", () => {
  it("accepts the symbols argon carries, trimmed + upper-cased", () => {
    for (const [raw, want] of [
      ["AAPL", "AAPL"],
      ["aapl", "AAPL"],
      ["brk.b", "BRK.B"],
      ["BRK-B", "BRK-B"],
      ["^VIX", "^VIX"],
      ["^vix", "^VIX"],
      ["SPX", "SPX"],
      ["  spy  ", "SPY"],
    ] as const) {
      expect(normalizeTicker(raw)).toBe(want);
    }
  });

  it("rejects traversal, separators, empty and overlong values", () => {
    for (const bad of [
      "../%68%65%61%6c%74%68#", // the observed probe → /api/health
      "../health",
      "a/b",
      "%2e%2e",
      "..%2f",
      "",
      "   ",
      "..",
      ".",
      "AAAAAAAAAAA", // 11 chars
      "AA PL",
      "AAPL?",
      "AAPL#x",
    ]) {
      expect(() => normalizeTicker(bad)).toThrow(/invalid ticker/);
    }
  });
});
