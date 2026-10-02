// Parity proof for returnDistribution: on the frozen real /technicals payloads
// (tests/fixtures/mcp, see its README), every value must deep-equal what
// ReturnHistogram computed before the extraction — the same inline expressions
// copied below as the oracle. The literal anchors were computed once from the
// fixtures at authoring time (2026-10-02) and pinned here.
import { describe, expect, it } from "vitest";
import type { TechnicalsResponse } from "@/lib/api";
import {
  returnBins,
  returnDistribution,
} from "@/lib/technicals/returnDistribution";
import aapl from "@/tests/fixtures/mcp/aapl_technicals.json";
import nvda from "@/tests/fixtures/mcp/nvda_technicals.json";
import spy from "@/tests/fixtures/mcp/spy_technicals.json";

function normPdf(x: number, mean: number, sd: number): number {
  const z = (x - mean) / sd;
  return Math.exp(-0.5 * z * z) / (sd * Math.sqrt(2 * Math.PI));
}

// The pre-extraction component body, verbatim: simple returns over non-null
// closes, last WINDOW = 60, Fisher-Pearson skew, normal overlay in count units.
function expected(data: TechnicalsResponse) {
  const closes = (data.series ?? [])
    .map((r) => r.close)
    .filter((v): v is number => v != null);
  const rets: number[] = [];
  for (let i = 1; i < closes.length; i++) {
    const p = closes[i - 1];
    if (p) rets.push(closes[i] / p - 1);
  }
  const window = rets.slice(-60);
  const bins = returnBins(window, 21);
  const n = window.length;
  const { edges, mean, sd } = bins;
  const fitted = n >= 20 && sd > 0;
  const skew = fitted
    ? (n / ((n - 1) * (n - 2))) *
      window.reduce((a, c) => a + ((c - mean) / sd) ** 3, 0)
    : null;
  const lo = edges[0];
  const hi = edges[edges.length - 1];
  const w = (hi - lo) / 21;
  const normal = fitted
    ? Array.from({ length: 121 }, (_, i) => {
        const x = lo + ((hi - lo) * i) / 120;
        return { x, count: n * w * normPdf(x, mean, sd) };
      })
    : null;
  return { n, mean, sd, skew, bins, normal };
}

const CASES: {
  ticker: string;
  fixture: TechnicalsResponse;
  anchors: { n: number; mean: number; sd: number; skew: number };
}[] = [
  {
    ticker: "AAPL",
    fixture: aapl as unknown as TechnicalsResponse,
    anchors: {
      n: 60,
      mean: 0.00250425958803994,
      sd: 0.02020646143296038,
      skew: -0.9805203821666229,
    },
  },
  {
    ticker: "NVDA",
    fixture: nvda as unknown as TechnicalsResponse,
    anchors: {
      n: 60,
      mean: 0.002169606710686239,
      sd: 0.025057428819983987,
      skew: 0.45087514806901874,
    },
  },
  {
    ticker: "SPY",
    fixture: spy as unknown as TechnicalsResponse,
    anchors: {
      n: 60,
      mean: 0.0006595606486352656,
      sd: 0.007128292473864062,
      skew: 0.44952560207148073,
    },
  },
];

describe("returnDistribution", () => {
  for (const { ticker, fixture, anchors } of CASES) {
    describe(ticker, () => {
      const d = returnDistribution(fixture.series);
      const x = expected(fixture);

      it("reproduces the window stats and skew", () => {
        expect(d.n).toBe(x.n);
        expect(d.mean).toBe(x.mean);
        expect(d.sd).toBe(x.sd);
        expect(d.skew).toEqual(x.skew);
      });

      it("reproduces the histogram bins", () => {
        expect(d.bins).toEqual(x.bins);
      });

      it("reproduces the normal overlay in count units", () => {
        expect(d.normal).toEqual(x.normal);
      });

      it("matches the pinned anchors", () => {
        expect(d.n).toBe(anchors.n);
        expect(d.mean).toBeCloseTo(anchors.mean, 12);
        expect(d.sd).toBeCloseTo(anchors.sd, 12);
        expect(d.skew).toBeCloseTo(anchors.skew, 12);
        expect(d.bins.counts.reduce((a, c) => a + c, 0)).toBe(d.n);
      });
    });
  }

  it("degenerates cleanly on empty and tiny inputs", () => {
    const empty = returnDistribution([]);
    expect(empty.n).toBe(0);
    expect(empty.sd).toBe(0);
    expect(empty.skew).toBeNull();
    expect(empty.normal).toBeNull();
    const one = returnDistribution([{ close: 10 } as never]);
    expect(one.n).toBe(0); // one close → zero returns
    const flat = returnDistribution(
      Array.from({ length: 30 }, () => ({ close: 50 }) as never),
    );
    expect(flat.n).toBe(29); // 30 closes → 29 zero returns
    expect(flat.sd).toBe(0); // zero-variance returns → no fit
    expect(flat.skew).toBeNull();
    expect(flat.normal).toBeNull();
  });
});
