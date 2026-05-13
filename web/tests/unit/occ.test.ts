import { describe, expect, it } from "vitest";
import { parseOccSymbol } from "@/lib/occ";

describe("parseOccSymbol", () => {
  it("parses a standard put", () => {
    expect(parseOccSymbol("GOOGL260612P00335000")).toEqual({
      root: "GOOGL",
      expiry: "2026-06-12",
      type: "P",
      strike: 335,
    });
  });

  it("parses a standard call with fractional strike", () => {
    expect(parseOccSymbol("AAPL260117C00187500")).toEqual({
      root: "AAPL",
      expiry: "2026-01-17",
      type: "C",
      strike: 187.5,
    });
  });

  it("returns null for malformed input", () => {
    expect(parseOccSymbol("NOT-A-SYMBOL")).toBeNull();
    expect(parseOccSymbol("")).toBeNull();
    expect(parseOccSymbol("GOOGL260612X00335000")).toBeNull();
  });

  it("returns null for impossible date (Feb 30)", () => {
    expect(parseOccSymbol("AAPL260230C00100000")).toBeNull();
  });

  it("parses a short root with trailing space padding", () => {
    expect(parseOccSymbol("F   260612C00012500")).toEqual({
      root: "F",
      expiry: "2026-06-12",
      type: "C",
      strike: 12.5,
    });
  });
});
