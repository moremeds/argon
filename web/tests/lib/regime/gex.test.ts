// Pure-function parity tests for web/lib/regime/derive/gex.ts on the frozen
// regime fixtures. The `oracle*` functions are verbatim copies of the inline
// expressions removed from components/regime/GexSubTab.tsx (the only
// adaptation is an injected `now` where the original read Date.now()).
//
// Clock injection: regime_quotes.json carries fresh_within_seconds = 900 and
// quotes[].quoted_at ≈ 2026-07-11T11:59Z+08:00 while the payload's own as_of
// is 2026-09-23T22:10Z+08:00. Tests set `now` relative to a quote's quoted_at
// for the fresh path and relative to the payload as_of for the stale path.
import { describe, expect, it } from "vitest";
import gexFixture from "../../fixtures/mcp/regime_gex.json";
import quotesFixture from "../../fixtures/mcp/regime_quotes.json";
import {
  gexSpotRead,
  liveSpotSelection,
  retagProfileForSpot,
} from "@/lib/regime/derive/gex";
import type { GexBucket, GexData, GexLevel } from "@/lib/regime/useGex";
import type { RegimeQuotesResponse } from "@/lib/regime/useRegimeQuotes";

const data = gexFixture as unknown as GexData;
const quotes = quotesFixture as unknown as RegimeQuotesResponse;

/* ─── oracles: the original inline expressions, verbatim ─── */

const DEFAULT_FRESH_SECONDS = 900;
function oracleFresh(
  quotedAt: string | null | undefined,
  freshWithinSeconds: number = DEFAULT_FRESH_SECONDS,
  now: number,
): boolean {
  if (!quotedAt) return false;
  return now - new Date(quotedAt).getTime() < freshWithinSeconds * 1000;
}

function oracleLiveSpot(
  d: GexData | undefined,
  q: RegimeQuotesResponse | undefined,
  now: number,
): { liveSpot: number | null; spotTapeTime: string | null | undefined } {
  const spxQuote = d?.ticker === "SPX" ? q?.quotes?.SPX : undefined;
  const quoteAtMs = spxQuote?.quoted_at ? Date.parse(spxQuote.quoted_at) : NaN;
  const tapeMs = d?.tape_time ? Date.parse(d.tape_time) : NaN;
  const quoteNotBehindTape =
    !Number.isFinite(quoteAtMs) || !Number.isFinite(tapeMs)
      ? true
      : quoteAtMs >= tapeMs;
  const liveSpot =
    spxQuote &&
    quoteNotBehindTape &&
    oracleFresh(spxQuote.quoted_at, q?.fresh_within_seconds, now)
      ? spxQuote.price
      : null;
  const spotTapeTime = liveSpot != null ? spxQuote?.quoted_at : d?.tape_time;
  return { liveSpot, spotTapeTime };
}

function oracleReads(d: GexData, liveSpot: number | null) {
  const displaySpot = liveSpot ?? d.spot;
  const prevClose =
    d.prev_close != null && d.prev_close > 0 ? d.prev_close : null;
  const dayChange =
    liveSpot != null && prevClose != null
      ? liveSpot - prevClose
      : d.day_change;
  const dayChangePct =
    liveSpot != null && prevClose != null
      ? ((liveSpot - prevClose) / prevClose) * 100
      : d.day_change_pct;
  return { displaySpot, prevClose, dayChange, dayChangePct };
}

function oracleRetag(
  profile: GexBucket[],
  liveSpot: number,
  levels:
    | {
        gex_flip?: GexLevel;
        max_magnet?: GexLevel;
        second_magnet?: GexLevel;
        max_accelerator?: GexLevel;
        put_wall?: GexLevel;
        call_wall?: GexLevel;
      }
    | null
    | undefined,
): GexBucket[] {
  if (!profile.length) return profile;
  let nearest: number | null = null;
  let minDist = Infinity;
  for (const b of profile) {
    const d = Math.abs(b.strike - liveSpot);
    if (d < minDist) {
      minDist = d;
      nearest = b.strike;
    }
  }
  const tagMap = new Map<number, string>();
  if (nearest != null) tagMap.set(nearest, "SPOT");
  if (levels?.gex_flip) tagMap.set(levels.gex_flip.strike, "GEX FLIP");
  const labelled: [GexLevel, string][] = [
    [levels?.max_magnet ?? null, "MAX MAGNET"],
    [levels?.second_magnet ?? null, "SECOND MAGNET"],
    [levels?.max_accelerator ?? null, "MAX ACCELERATOR"],
    [levels?.put_wall ?? null, "PUT WALL"],
    [levels?.call_wall ?? null, "CALL WALL"],
  ];
  for (const [level, label] of labelled) {
    if (level && !tagMap.has(level.strike)) tagMap.set(level.strike, label);
  }
  return profile.map((b) => ({
    ...b,
    pct_from_spot: ((b.strike - liveSpot) / liveSpot) * 100,
    tag: tagMap.get(b.strike) ?? null,
  }));
}

/* ─── clock anchor: 60 s after the SPX quote's quoted_at → fresh ─── */
const nowFresh = Date.parse(quotes.quotes!.SPX.quoted_at) + 60_000;
const nowStale = Date.parse(quotes.as_of!); // months past quoted_at → stale

describe("liveSpotSelection", () => {
  it("uses the SPX quote when fresh and not behind tape_time", () => {
    const r = liveSpotSelection(data.ticker, data.tape_time, quotes, nowFresh);
    const o = oracleLiveSpot(data, quotes, nowFresh);
    expect(r).toEqual(o);
    expect(r.liveSpot).toBe(7575.39);
    expect(r.spotTapeTime).toBe("2026-07-11T11:59:47.227000+08:00");
  });

  it("returns null liveSpot and the payload tape_time when stale", () => {
    const r = liveSpotSelection(data.ticker, data.tape_time, quotes, nowStale);
    expect(r.liveSpot).toBeNull();
    expect(r.spotTapeTime).toBe(data.tape_time); // fixture: null
    expect(r).toEqual(oracleLiveSpot(data, quotes, nowStale));
  });

  it("rejects a quote older than tape_time even inside the fresh window", () => {
    const tape = "2026-07-11T12:30:00+08:00";
    const r = liveSpotSelection(data.ticker, tape, quotes, nowFresh);
    expect(r.liveSpot).toBeNull();
    expect(r.spotTapeTime).toBe(tape);
    const o = oracleLiveSpot({ ...data, tape_time: tape }, quotes, nowFresh);
    expect(r.liveSpot).toBe(o.liveSpot);
  });

  it("ignores the quote for a non-SPX ticker", () => {
    expect(
      liveSpotSelection("SPY", data.tape_time, quotes, nowFresh).liveSpot,
    ).toBeNull();
  });
});

describe("gexSpotRead", () => {
  it("live spot rebases displaySpot", () => {
    const r = gexSpotRead(data, 7575.39);
    expect(r).toEqual(oracleReads(data, 7575.39));
    expect(r.displaySpot).toBe(7575.39);
  });

  it("prev_close null counts as missing → payload day-change pass-through", () => {
    const r = gexSpotRead(data, 7575.39);
    expect(r.prevClose).toBeNull();
    expect(r.dayChange).toBe(data.day_change); // fixture: null
    expect(r.dayChangePct).toBe(data.day_change_pct);
  });

  it("prev_close ≤ 0 also counts as missing", () => {
    const d = { ...data, prev_close: 0, day_change: 1.25, day_change_pct: 0.02 };
    const r = gexSpotRead(d, 7575.39);
    expect(r.prevClose).toBeNull();
    expect(r.dayChange).toBe(1.25);
    expect(r.dayChangePct).toBe(0.02);
  });

  it("computes live day change when prev_close is usable", () => {
    const d = { ...data, prev_close: 7500, day_change: 1, day_change_pct: 1 };
    const r = gexSpotRead(d, 7575.39);
    expect(r.dayChange).toBeCloseTo(75.39, 10);
    expect(r.dayChangePct).toBeCloseTo((75.39 / 7500) * 100, 10);
    expect(r).toEqual(oracleReads(d, 7575.39));
  });

  it("no live spot → payload spot pass-through", () => {
    const r = gexSpotRead(data, null);
    expect(r.displaySpot).toBe(7716.87);
    expect(r).toEqual(oracleReads(data, null));
  });
});

describe("retagProfileForSpot", () => {
  it("matches the verbatim oracle across the fixture profile", () => {
    expect(retagProfileForSpot(data.profile, 7575.39, data.levels)).toEqual(
      oracleRetag(data.profile, 7575.39, data.levels),
    );
  });

  it("anchors: SPOT lands on 7575, GEX FLIP stays on 7725", () => {
    const tagged = retagProfileForSpot(data.profile, 7575.39, data.levels);
    expect(tagged).toHaveLength(62);
    expect(
      tagged.filter((b) => b.tag === "SPOT").map((b) => b.strike),
    ).toEqual([7575]);
    expect(
      tagged.filter((b) => b.tag === "GEX FLIP").map((b) => b.strike),
    ).toEqual([7725]);
    expect(tagged[0].strike).toBe(6950);
    expect(tagged[0].pct_from_spot).toBeCloseTo(
      ((6950 - 7575.39) / 7575.39) * 100,
      12,
    );
  });

  it("empty profile returns the input unchanged", () => {
    const empty: GexBucket[] = [];
    expect(retagProfileForSpot(empty, 7575.39, data.levels)).toBe(empty);
  });
});
