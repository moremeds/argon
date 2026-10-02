// greeksNet — oracle is the shared local block from CharmPanel/VannaPanel
// (expiry sort, default-expiry pick, per-strike net, |net| < 1000 tone),
// pinned on the frozen *_stock.json payloads plus literal branch cases.
import { describe, expect, it } from "vitest";
import type { components } from "@/lib/types";
import {
  defaultExpiry,
  netExposureCurve,
  netExposureTone,
  sortByExpiry,
  type ExposuresSummaryRow,
  type StrikeExposureRow,
} from "@/lib/snapshot/greeksNet";
import aapl from "@/tests/fixtures/mcp/aapl_stock.json";
import nvda from "@/tests/fixtures/mcp/nvda_stock.json";
import spy from "@/tests/fixtures/mcp/spy_stock.json";

type Report = components["schemas"]["SingleStockReport"];

const STOCK = {
  AAPL: aapl as unknown as Report,
  NVDA: nvda as unknown as Report,
  SPY: spy as unknown as Report,
};

const toNum = (v: string | number | null | undefined): number | null => {
  if (v == null) return null;
  const x = typeof v === "number" ? v : Number(v);
  return Number.isFinite(x) ? x : null;
};

describe("default expiry on frozen payloads", () => {
  it.each(Object.entries(STOCK))(
    "%s picks the first live expiry (2026-09-18, dte 0)",
    (_t, rep) => {
      const sorted = sortByExpiry(rep.exposures_summary!);
      // Oracle: verbatim from the panels.
      const oracleSorted = [...rep.exposures_summary!].sort((a, b) =>
        a.expiry < b.expiry ? -1 : 1,
      );
      expect(sorted).toEqual(oracleSorted);
      const live = sorted
        .filter((r) => r.dte == null || (r.dte as number) >= 0)
        .sort(
          (a, b) => ((a.dte ?? 99999) as number) - ((b.dte ?? 99999) as number),
        );
      const expected = (live[0] ?? sorted[0])?.expiry ?? null;
      expect(defaultExpiry(sorted)).toBe(expected);
      expect(defaultExpiry(sorted)).toBe("2026-09-18");
    },
  );

  it("falls back to the earliest sorted expiry when none are live", () => {
    const summary = [
      { expiry: "2026-02-01", dte: -3 },
      { expiry: "2026-01-01", dte: -10 },
    ] as ExposuresSummaryRow[];
    expect(defaultExpiry(sortByExpiry(summary))).toBe("2026-01-01");
    expect(defaultExpiry([])).toBeNull();
  });

  it("dte null counts as live", () => {
    const summary = [
      { expiry: "2026-03-01", dte: null },
      { expiry: "2026-01-01", dte: 5 },
    ] as ExposuresSummaryRow[];
    // null dte sorts as 99999 → the 5-dte row wins the live pick
    expect(defaultExpiry(sortByExpiry(summary))).toBe("2026-01-01");
  });
});

describe("netExposureCurve", () => {
  it("nets call+put per strike, sorted, on the fixture's covered expiry", () => {
    const rows = (STOCK.SPY.strike_exposures ?? []).filter(
      (r) => r.expiry === "2026-09-21",
    );
    expect(rows.length).toBeGreaterThan(0);
    const curve = netExposureCurve(rows, "vanna");
    const oracle = rows
      .map((r) => ({
        strike: toNum(r.strike) ?? NaN,
        netValue: (toNum(r.call_vanna) ?? 0) + (toNum(r.put_vanna) ?? 0),
      }))
      .filter((p) => Number.isFinite(p.strike))
      .sort((a, b) => a.strike - b.strike);
    expect(curve).toEqual(oracle);
    expect(curve.length).toBe(155);
    for (let i = 1; i < curve.length; i++)
      expect(curve[i].strike).toBeGreaterThanOrEqual(curve[i - 1].strike);
  });

  it("is empty when no strike rows match the default expiry", () => {
    // The frozen payloads' strike_exposures only cover 2026-09-21, while the
    // default summary expiry is 2026-09-18 — same empty curve the panel draws.
    const rows = (STOCK.AAPL.strike_exposures ?? []).filter(
      (r) => r.expiry === "2026-09-18",
    );
    expect(netExposureCurve(rows, "charm")).toEqual([]);
  });

  it("drops non-finite strikes and coerces missing legs to 0", () => {
    const rows = [
      { strike: "100", expiry: "e", call_charm: "2", put_charm: "3" },
      { strike: "abc", expiry: "e", call_charm: "9", put_charm: "9" },
      { strike: "105", expiry: "e", call_charm: "1" },
    ] as StrikeExposureRow[];
    expect(netExposureCurve(rows, "charm")).toEqual([
      { strike: 100, netValue: 5 },
      { strike: 105, netValue: 1 },
    ]);
  });

  it("keeps an empty-string strike at 0, as the panels' local toNum does", () => {
    const rows = [
      { strike: "", expiry: "e", call_charm: "9", put_charm: "9" },
      { strike: "100", expiry: "e", call_charm: "2", put_charm: "3" },
    ] as StrikeExposureRow[];
    expect(netExposureCurve(rows, "charm")).toEqual([
      { strike: 0, netValue: 18 },
      { strike: 100, netValue: 5 },
    ]);
  });
});

describe("netExposureTone", () => {
  it("matches the panels' |net| < 1000 → muted rule", () => {
    expect(netExposureTone(null)).toBe("muted");
    expect(netExposureTone(0)).toBe("muted");
    expect(netExposureTone(999)).toBe("muted");
    expect(netExposureTone(-999)).toBe("muted");
    expect(netExposureTone(1000)).toBe("positive");
    expect(netExposureTone(-1000)).toBe("negative");
    expect(netExposureTone(1e9)).toBe("positive");
  });

  it("pins the frozen net greeks and tones", () => {
    const sum = (rep: Report, expiry: string) =>
      rep.exposures_summary!.find((r) => r.expiry === expiry)!;
    // Default expiry is 2026-09-18 on all three fixtures.
    expect(toNum(sum(STOCK.AAPL, "2026-09-18").net_charm)).toBeCloseTo(
      307993288.3055,
      4,
    );
    expect(netExposureTone(toNum(sum(STOCK.AAPL, "2026-09-18").net_vanna))).toBe(
      "negative",
    );
    expect(netExposureTone(toNum(sum(STOCK.NVDA, "2026-09-18").net_vanna))).toBe(
      "positive",
    );
    expect(netExposureTone(toNum(sum(STOCK.SPY, "2026-09-18").net_vanna))).toBe(
      "positive",
    );
  });
});
