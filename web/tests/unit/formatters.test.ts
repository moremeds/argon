import { describe, expect, it } from "vitest";
import {
  fmtDateTimeWithZone,
  fmtDecimal,
  fmtMoney,
  fmtMoneyAbbrev,
  fmtPct,
  fmtRelativeAgo,
  fmtRelativeDay,
  fmtSigned,
  fmtTimeOfDay,
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

describe("fmtMoneyAbbrev", () => {
  it("formats values >= 1T with T suffix", () => {
    expect(fmtMoneyAbbrev(1_500_000_000_000)).toBe("+$1.5T");
    expect(fmtMoneyAbbrev(-1_500_000_000_000)).toBe("-$1.5T");
  });
  it("formats millions, thousands", () => {
    expect(fmtMoneyAbbrev(1_300_000)).toBe("+$1.3M");
    expect(fmtMoneyAbbrev(-227_050)).toBe("-$227.1K");
    expect(fmtMoneyAbbrev(0)).toBe("$0");
  });
  it("returns dash for null/undefined", () => {
    expect(fmtMoneyAbbrev(null)).toBe("—");
    expect(fmtMoneyAbbrev(undefined)).toBe("—");
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
      /^\d{4}\/\d{2}\/\d{2} \d{2}:\d{2}:\d{2} (?:GMT[+-]\d{1,2}|UTC|HKG|[A-Z]{2,5})$/,
    );
    expect(formatted).not.toContain("May");
  });

  it("uses HKG as the compact label for Hong Kong time", () => {
    expect(
      fmtDateTimeWithZone("2026-05-14T00:54:48Z", {
        timeZone: "Asia/Hong_Kong",
      }),
    ).toBe("2026/05/14 08:54:48 HKG");
  });

  it("renders a dash for missing timestamps", () => {
    expect(fmtDateTimeWithZone(null)).toBe("—");
  });
});

describe("fmtTimeOfDay", () => {
  it("renders HH:MM:SS for a fixed timezone", () => {
    expect(
      fmtTimeOfDay("2026-05-19T18:23:05Z", { timeZone: "America/New_York" }),
    ).toBe("14:23:05");
  });
  it("returns em-dash for null / invalid", () => {
    expect(fmtTimeOfDay(null)).toBe("—");
    expect(fmtTimeOfDay("not a date")).toBe("—");
  });
});

describe("fmtRelativeAgo", () => {
  const NOW = new Date("2026-05-19T20:00:00Z");
  it("seconds for sub-minute deltas", () => {
    expect(fmtRelativeAgo("2026-05-19T19:59:45Z", NOW)).toBe("15s ago");
  });
  it("minutes for sub-hour deltas", () => {
    expect(fmtRelativeAgo("2026-05-19T19:35:00Z", NOW)).toBe("25m ago");
  });
  it("hours-and-minutes for >=1h, <24h", () => {
    expect(fmtRelativeAgo("2026-05-19T17:45:00Z", NOW)).toBe("2h 15m ago");
  });
  it("trims minutes when zero", () => {
    expect(fmtRelativeAgo("2026-05-19T17:00:00Z", NOW)).toBe("3h ago");
  });
  it("days for >=24h", () => {
    expect(fmtRelativeAgo("2026-05-17T20:00:00Z", NOW)).toBe("2d ago");
  });
  it("flags future timestamps explicitly", () => {
    expect(fmtRelativeAgo("2026-05-19T21:00:00Z", NOW)).toBe("in future");
  });
  it("em-dash for null", () => {
    expect(fmtRelativeAgo(null, NOW)).toBe("—");
  });
});

describe("fmtRelativeDay", () => {
  const TODAY = new Date("2026-05-19T14:00:00Z");
  it("renders 'today' for same UTC date", () => {
    expect(fmtRelativeDay("2026-05-19", TODAY)).toBe("today");
  });
  it("renders 'yesterday' for prior day", () => {
    expect(fmtRelativeDay("2026-05-18", TODAY)).toBe("yesterday");
  });
  it("renders 'Nd ago' for older dates", () => {
    expect(fmtRelativeDay("2026-05-15", TODAY)).toBe("4d ago");
  });
  it("flags future dates", () => {
    expect(fmtRelativeDay("2026-05-20", TODAY)).toBe("in future");
  });
  it("accepts ISO datetimes (slices to date)", () => {
    expect(fmtRelativeDay("2026-05-18T23:59:59Z", TODAY)).toBe("yesterday");
  });
  it("em-dash for null", () => {
    expect(fmtRelativeDay(null, TODAY)).toBe("—");
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
