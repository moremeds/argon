import { describe, expect, it } from "vitest";
import {
  bollinger,
  ema,
  fmtVolCompact,
  highVolMarkers,
  lowestInWindow,
  lowVolMarkers,
  prevCloseUp,
  rollingStd,
  sma,
  volumeMa,
} from "@/lib/indicators";
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

describe("prevCloseUp", () => {
  it("colors by previous close, falling back to open on the first bar", () => {
    const up = prevCloseUp(SPY_BARS);
    expect(up[0]).toBe(true); // 650.34 >= open 638.94 (no prev close)
    expect(up[1]).toBe(true); // 655.24 >= 650.34
    // 2026-07-08: close 745.40 > open 743.16 (green candle) but < prev close
    // 747.71 — the case where prev-close coloring DIFFERS from bar direction.
    expect(SPY_BARS[67].as_of).toBe("2026-07-08");
    expect(up[67]).toBe(false);
  });

  it("emits null when close is null", () => {
    expect(prevCloseUp([{ close: null, open: 1 }])).toEqual([null]);
  });
});

describe("lowestInWindow", () => {
  it("flags trailing-10 minima on real SPY volume (pandas rolling(10).min parity)", () => {
    const flags = lowestInWindow(
      SPY_BARS.map((b) => b.volume),
      10,
    );
    const dates = SPY_BARS.filter((_, i) => flags[i]).map((b) => b.as_of);
    expect(dates).toEqual([
      "2026-04-27",
      "2026-05-21",
      "2026-05-22",
      "2026-05-26",
      "2026-06-02",
      "2026-06-22",
      "2026-07-07",
      "2026-07-09",
    ]);
  });
});

describe("volumeMa / fmtVolCompact", () => {
  it("MA50 matches pandas on real SPY volume", () => {
    const ma = volumeMa(
      SPY_BARS.map((b) => b.volume),
      50,
    );
    expect(ma[48]).toBeNull();
    expect(ma[49]).toBeCloseTo(55241595.14, 2);
    expect(ma[69]).toBeCloseTo(53919783.64, 2);
  });

  it("formats K/M/B", () => {
    expect(fmtVolCompact(42431978)).toBe("42.43M");
    expect(fmtVolCompact(152534102)).toBe("152.53M");
    expect(fmtVolCompact(1234)).toBe("1.23K");
    expect(fmtVolCompact(999)).toBe("999");
    expect(fmtVolCompact(2500000000)).toBe("2.5B");
  });
});

describe("lowVolMarkers", () => {
  const ma = volumeMa(
    SPY_BARS.map((b) => b.volume),
    50,
  );
  it("no bar is 25% below MA50 on this fixture", () => {
    expect(lowVolMarkers(SPY_BARS, ma, { thresholdPct: -25, color: "#888" })).toEqual([]);
  });
  it("fires at -20% and labels the rounded deficit", () => {
    const m = lowVolMarkers(SPY_BARS, ma, { thresholdPct: -20, color: "#888" });
    const last = m.find((x) => x.time === "2026-07-10");
    expect(last).toBeDefined();
    expect(last!.text).toBe("-21%"); // vol 42,431,978 vs MA50 53,919,783.64 → -21.3%
    expect(last!.position).toBe("belowBar");
  });
});

describe("highVolMarkers", () => {
  it("labels exactly the fixture's volume peak (HVE, first bar)", () => {
    const m = highVolMarkers(SPY_BARS, { color: "#ccc" });
    expect(m).toHaveLength(1);
    expect(m[0].time).toBe("2026-03-31");
    expect(m[0].position).toBe("aboveBar");
    // text: tag + compact volume + price change% (close vs open on bar 0)
    expect(m[0].text).toBe("HVE 152.53M +1.78%");
  });
});
