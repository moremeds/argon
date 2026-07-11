import { describe, expect, it } from "vitest";
import { bollinger, ema, rollingStd, sma } from "@/lib/indicators";
import { SPY_BARS } from "./fixtures/spyBars";

// Expected values computed independently with pandas at plan-authoring time
// (2026-07-11) from this exact fixture:
//   ema  <-> close.ewm(span=N, adjust=False).mean()
//   sma  <-> close.rolling(N).mean()
//   std  <-> close.rolling(N).std(ddof=0)   (population — Bollinger convention)
// DO NOT edit these constants to make tests pass.
const closes = SPY_BARS.map((b) => b.close);

describe("ema", () => {
  it("matches pandas ewm(span, adjust=False) on real SPY closes", () => {
    const e5 = ema(closes, 5);
    const e20 = ema(closes, 20);
    const e50 = ema(closes, 50);
    expect(e5[0]).toBeCloseTo(650.34, 10); // seeded at first value
    expect(e5[4]).toBeCloseTo(656.5061728395062, 8);
    expect(e5[30]).toBeCloseTo(737.3643335649523, 8);
    expect(e5[69]).toBeCloseTo(750.2677023210776, 8);
    expect(e20[19]).toBeCloseTo(693.2104087055366, 8);
    expect(e20[69]).toBeCloseTo(744.9080264611164, 8);
    expect(e50[49]).toBeCloseTo(721.5231677698386, 8);
    expect(e50[69]).toBeCloseTo(734.1239811340163, 8);
  });

  it("emits null for null input and carries state across it", () => {
    const out = ema([10, null, 20], 5);
    expect(out[0]).toBeCloseTo(10, 10);
    expect(out[1]).toBeNull();
    // state carried: e = (2/6)*20 + (4/6)*10 = 13.333...
    expect(out[2]).toBeCloseTo(13.333333333333334, 10);
  });
});

describe("sma / rollingStd", () => {
  it("matches pandas rolling on real SPY closes", () => {
    const s20 = sma(closes, 20);
    const d20 = rollingStd(closes, 20);
    expect(s20[18]).toBeNull(); // warmup
    expect(s20[19]).toBeCloseTo(689.025, 8);
    expect(s20[69]).toBeCloseTo(743.8115, 8);
    expect(d20[19]).toBeCloseTo(22.296483018628784, 6);
    expect(d20[69]).toBeCloseTo(7.175446519207074, 6);
  });

  it("nulls any window containing a null", () => {
    const vals = [1, 2, null, 4, 5, 6];
    const out = sma(vals, 3);
    expect(out).toEqual([null, null, null, null, null, 5]);
  });
});

describe("bollinger", () => {
  it("mid ± 2·population-std on real SPY closes", () => {
    const bb = bollinger(closes, 20, 2);
    expect(bb.upper[18]).toBeNull();
    expect(bb.upper[69]).toBeCloseTo(758.1623930384142, 6);
    expect(bb.lower[69]).toBeCloseTo(729.4606069615859, 6);
  });
});
