import { describe, expect, it } from "vitest";
import {
  fmtDateTimeWithZone,
  fmtDecimal,
  fmtMoney,
  fmtPct,
  fmtSigned,
  toNum,
} from "@/lib/formatters";

describe("fmtPct", () => {
  it("formats decimal percent", () => {
    expect(fmtPct(0.293)).toBe("29.3%");
    expect(fmtPct(-0.044)).toBe("-4.4%");
  });
  it("renders em-dash for null", () => {
    expect(fmtPct(null)).toBe("—");
  });
});

describe("fmtMoney", () => {
  it("formats large numbers with commas, no decimals", () => {
    expect(fmtMoney(91_000_000)).toBe("$91,000,000");
  });
  it("handles negative", () => {
    expect(fmtMoney(-50_000_000)).toBe("-$50,000,000");
  });
  it("prefixes positives with + when signed", () => {
    expect(fmtMoney(1_748_151, { signed: true })).toBe("+$1,748,151");
    expect(fmtMoney(-50_000_000, { signed: true })).toBe("-$50,000,000");
    expect(fmtMoney(0, { signed: true })).toBe("+$0");
  });
});

describe("fmtSigned", () => {
  it("prefixes positive with +", () => {
    expect(fmtSigned(0.05, 2)).toBe("+0.05");
    expect(fmtSigned(-0.05, 2)).toBe("-0.05");
  });
});

describe("fmtDecimal", () => {
  it("formats with configurable digits", () => {
    expect(fmtDecimal(81256, 0)).toBe("81,256");
    expect(fmtDecimal(0.691, 4)).toBe("0.6910");
  });
});

describe("fmtDateTimeWithZone", () => {
  it("renders a compact date, time, and timezone", () => {
    const formatted = fmtDateTimeWithZone("2026-05-14T00:54:48Z");
    expect(formatted).toMatch(
      /^\d{4}\/\d{2}\/\d{2} \d{2}:\d{2}:\d{2} (?:GMT[+-]\d{1,2}|UTC|[A-Z]{2,5})$/,
    );
    expect(formatted).not.toContain("May");
  });

  it("renders a dash for missing timestamps", () => {
    expect(fmtDateTimeWithZone(null)).toBe("—");
  });
});

describe("toNum", () => {
  it("preserves zero", () => {
    expect(toNum(0)).toBe(0);
    expect(toNum("0")).toBe(0);
  });
  it("returns null for null/undefined/empty", () => {
    expect(toNum(null)).toBeNull();
    expect(toNum(undefined)).toBeNull();
    expect(toNum("")).toBeNull();
  });
  it("returns null for non-numeric strings", () => {
    expect(toNum("abc")).toBeNull();
  });
  it("parses numeric strings", () => {
    expect(toNum("1.5")).toBe(1.5);
  });
});
