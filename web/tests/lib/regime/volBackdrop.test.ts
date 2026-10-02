// Pure-function parity tests for web/lib/regime/derive/volBackdrop.ts on the
// frozen regime fixtures. The `oracle*` functions are verbatim copies of the
// inline expressions removed from components/regime/VolBackdropStrip.tsx (the
// only adaptation is an injected `now` where the original quoteIsFresh read
// Date.now()).
//
// Clock injection: regime_quotes.json carries fresh_within_seconds = 900. The
// VIX leg's quoted_at (2026-07-11T11:59:47.460+08:00) is ~18 min behind the
// VIX3M leg (12:17:46.123+08:00), so a `now` inside both windows must be
// ≤ VIX quoted_at + 900 s. nowStale = the payload's as_of is months later →
// every quote stale → the EOD paths.
import { describe, expect, it } from "vitest";
import vbFixture from "../../fixtures/mcp/regime_vol_backdrop.json";
import quotesFixture from "../../fixtures/mcp/regime_quotes.json";
import {
  ratioSeries,
  symbolRead,
  termStructureRead,
} from "@/lib/regime/derive/volBackdrop";
import type { VolBackdropData } from "@/lib/regime/useVolBackdrop";
import type { RegimeQuotesResponse } from "@/lib/regime/useRegimeQuotes";

const data = vbFixture as unknown as VolBackdropData;
const quotes = quotesFixture as unknown as RegimeQuotesResponse;

/* ─── oracles: the original inline expressions, verbatim ─── */

function oracleFresh(
  quotedAt: string | null | undefined,
  freshWithinSeconds: number | undefined,
  now: number,
): boolean {
  if (!quotedAt) return false;
  return now - new Date(quotedAt).getTime() < (freshWithinSeconds ?? 900) * 1000;
}

function oracleLastClose(points: { close: number }[] | undefined): number | null {
  if (!points || !points.length) return null;
  return points[points.length - 1].close;
}

function oraclePctChange(points: { close: number }[] | undefined): number | null {
  if (!points || points.length < 2) return null;
  const prev = points[points.length - 2].close;
  const last = points[points.length - 1].close;
  if (!prev) return null;
  return ((last - prev) / prev) * 100;
}

function oracleTerm(
  d: VolBackdropData,
  q: RegimeQuotesResponse | null,
  now: number,
) {
  const freshWindow = q?.fresh_within_seconds;
  const qv = q?.quotes?.VIX;
  const q3 = q?.quotes?.VIX3M;
  const liveRatio =
    qv &&
    q3 &&
    oracleFresh(qv.quoted_at, freshWindow, now) &&
    oracleFresh(q3.quoted_at, freshWindow, now) &&
    q3.price
      ? qv.price / q3.price
      : null;
  const ratio = liveRatio ?? d.term_structure_ratio;
  const state =
    ratio != null
      ? ratio < 1
        ? "contango"
        : "backwardation"
      : d.term_structure_state;
  return { liveRatio, ratio, state };
}

function oracleSym(
  s: "VIX" | "VIX3M" | "VVIX" | "COR1M",
  d: VolBackdropData,
  q: RegimeQuotesResponse | null,
  now: number,
) {
  const freshWindow = q?.fresh_within_seconds;
  const qq = q?.quotes?.[s];
  const live = qq != null && oracleFresh(qq.quoted_at, freshWindow, now);
  const dailyClose = oracleLastClose(d.series[s]);
  const close = live ? qq.price : dailyClose;
  const chg =
    live && dailyClose
      ? ((qq.price - dailyClose) / dailyClose) * 100
      : oraclePctChange(d.series[s]);
  return { live, close, chg };
}

/* ─── clock anchors ─── */
// Inside both the VIX and VIX3M fresh windows (see file header).
const nowFresh =
  Math.min(
    Date.parse(quotes.quotes!.VIX.quoted_at),
    Date.parse(quotes.quotes!.VIX3M.quoted_at),
  ) + 60_000;
const nowStale = Date.parse(quotes.as_of!);

describe("termStructureRead", () => {
  it("uses the live VIX/VIX3M ratio when both legs are fresh", () => {
    const r = termStructureRead(data, quotes, nowFresh);
    const o = oracleTerm(data, quotes, nowFresh);
    expect(r.liveRatio).toBe(o.liveRatio);
    expect(r.ratio).toBe(o.ratio);
    expect(r.state).toBe(o.state);
    expect(r.liveRatio).toBeCloseTo(0.8093699515347333, 12);
    expect(r.ratioSource).toBe("live");
    expect(r.state).toBe("contango");
  });

  it("falls back to the EOD ratio when quotes are stale", () => {
    const r = termStructureRead(data, quotes, nowStale);
    expect(r.liveRatio).toBeNull();
    expect(r.ratio).toBe(0.811951754385965);
    expect(r.ratioSource).toBe("eod");
    expect(r.state).toBe("contango");
    expect(r).toMatchObject(oracleTerm(data, quotes, nowStale));
  });

  it("a zero VIX3M quote disables the live ratio", () => {
    const q = {
      ...quotes,
      quotes: { ...quotes.quotes, VIX3M: { ...quotes.quotes!.VIX3M, price: 0 } },
    };
    const r = termStructureRead(data, q, nowFresh);
    expect(r.liveRatio).toBeNull();
    expect(r.ratio).toBe(0.811951754385965);
  });

  it("no ratio at all keeps the payload state", () => {
    const d = {
      ...data,
      term_structure_ratio: null,
      term_structure_state: "backwardation" as const,
    };
    const r = termStructureRead(d, null, nowStale);
    expect(r.ratio).toBeNull();
    expect(r.state).toBe("backwardation");
  });

  it("ratio ≥ 1 reads backwardation", () => {
    const d = { ...data, term_structure_ratio: 1.02 };
    expect(termStructureRead(d, null, nowStale).state).toBe("backwardation");
  });
});

describe("symbolRead", () => {
  it("fresh quote → quote price with change vs last daily close", () => {
    const r = symbolRead("VIX", data, quotes, nowFresh);
    expect(r).toEqual(oracleSym("VIX", data, quotes, nowFresh));
    expect(r.live).toBe(true);
    expect(r.close).toBe(15.03);
    expect(r.chg).toBeCloseTo(1.4854827819041112, 12);
  });

  it("stale quote → last daily close and close-over-close", () => {
    const r = symbolRead("VIX", data, quotes, nowStale);
    expect(r.live).toBe(false);
    expect(r.close).toBe(14.81);
    expect(r.chg).toBeCloseTo(-4.08031088082901, 12);
    expect(r).toEqual(oracleSym("VIX", data, quotes, nowStale));
  });

  it.each([
    ["VIX3M", true, 18.57, 1.8092105263157996],
    ["VVIX", true, 87.28, -0.11444266422521666],
    ["COR1M", true, 3.35, -63.70530877573132],
  ] as const)("anchors %s fresh → %j", (sym, live, close, chg) => {
    const now = Date.parse(quotes.quotes![sym].quoted_at) + 60_000;
    const r = symbolRead(sym, data, quotes, now);
    expect(r.live).toBe(live);
    expect(r.close).toBe(close);
    expect(r.chg).toBeCloseTo(chg, 12);
    expect(r).toEqual(oracleSym(sym, data, quotes, now));
  });

  it("missing series → null close/chg", () => {
    const d = {
      ...data,
      series: { ...data.series, VIX: [] },
    };
    const r = symbolRead("VIX", d, null, nowStale);
    expect(r).toEqual({ live: false, close: null, chg: null });
  });
});

describe("ratioSeries", () => {
  it("joins VIX/VIX3M closes by date (verbatim oracle)", () => {
    const vix3mByDate = new Map(
      (data.series.VIX3M ?? []).map((p) => [p.date, p.close]),
    );
    const oracle = (data.series.VIX ?? []).map((p) => {
      const v3 = vix3mByDate.get(p.date);
      return v3 ? p.close / v3 : null;
    });
    expect(ratioSeries(data)).toEqual(oracle);
  });

  it("anchors: 55 points, 1 null (missing VIX3M date), last = EOD ratio", () => {
    const rs = ratioSeries(data);
    expect(rs).toHaveLength(55);
    expect(rs.filter((v) => v == null)).toHaveLength(1);
    expect(rs[rs.length - 1]).toBeCloseTo(0.811951754385965, 15);
  });
});
