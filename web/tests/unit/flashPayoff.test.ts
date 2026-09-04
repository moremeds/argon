import { describe, expect, it } from "vitest";

import type { Leg } from "@/components/flash/view";
import {
  intrinsic,
  payoffBreakpoints,
  payoffDomain,
  pnlAt,
} from "@/lib/flash/payoff";

/**
 * The recorded QQQ candidate of 2026-09-03 (`QQQ-2026-09-03-1`): a 710/665
 * put debit spread for a net 7.74 per share, expiring 2026-10-02. Max gain
 * 3726, max loss 774, breakeven 702.26 — all four are the run's own numbers,
 * and the point of these tests is that argon re-derives them from the LEGS
 * rather than trusting the model that wrote them.
 */
const LEGS: Leg[] = [
  { action: "buy", right: "put", strike: 710, expiry: "2026-10-02", mid: 10.45 },
  { action: "sell", right: "put", strike: 665, expiry: "2026-10-02", mid: 2.71 },
];
const NET = 7.74;
const SPOT = 717.47;
const BE = 702.26;

describe("intrinsic", () => {
  it("is zero for an OTM put", () => {
    expect(intrinsic("put", 665, SPOT)).toBe(0);
  });

  it("is K − S for an ITM put", () => {
    expect(intrinsic("put", 710, 700)).toBeCloseTo(10, 10);
  });

  it("is S − K for an ITM call", () => {
    expect(intrinsic("call", 710, 717.47)).toBeCloseTo(7.47, 10);
  });
});

describe("pnlAt", () => {
  it("loses the full debit at spot — both legs expire worthless", () => {
    expect(pnlAt(LEGS, NET, SPOT)).toBeCloseTo(-774, 8);
  });

  it("makes the recorded max gain far below the short strike", () => {
    expect(pnlAt(LEGS, NET, 600)).toBeCloseTo(3726, 8);
    expect(pnlAt(LEGS, NET, 0)).toBeCloseTo(3726, 8);
  });

  it("is flat at zero on the recorded breakeven", () => {
    expect(pnlAt(LEGS, NET, BE)).toBeCloseTo(0, 8);
    expect(BE).toBeCloseTo(710 - NET, 10);
  });

  it("slopes −100 per point between the strikes", () => {
    const a = pnlAt(LEGS, NET, 700);
    const b = pnlAt(LEGS, NET, 701);
    expect(b - a).toBeCloseTo(-100, 8);
  });

  it("is flat below the short strike — that is what caps the gain", () => {
    expect(pnlAt(LEGS, NET, 660) - pnlAt(LEGS, NET, 640)).toBeCloseTo(0, 8);
  });

  it("honours a ratio when the writer sent one", () => {
    const ratioed: Leg[] = [
      { ...LEGS[0], ratio: 2 },
      { ...LEGS[1], ratio: 1 },
    ];
    // Two long 710 puts, one short 665 put, at spot 700: 2*10 − 0 − net.
    expect(pnlAt(ratioed, NET, 700)).toBeCloseTo(100 * (20 - NET), 8);
  });
});

describe("payoffDomain", () => {
  it("pads 18% of the span on both sides", () => {
    const [lo, hi] = payoffDomain({
      strikes: [710, 665],
      spot: SPOT,
      breakeven: BE,
    });
    const span = SPOT - 665;
    expect(lo).toBeCloseTo(665 - 0.18 * span, 8);
    expect(hi).toBeCloseTo(SPOT + 0.18 * span, 8);
  });
});

describe("payoffBreakpoints", () => {
  const domain = payoffDomain({
    strikes: [710, 665],
    spot: SPOT,
    breakeven: BE,
  });

  it("returns exactly the five kinks, sorted", () => {
    expect(payoffBreakpoints({ strikes: [710, 665], breakeven: BE, domain })).toEqual(
      [domain[0], 665, BE, 710, domain[1]],
    );
  });

  it("drops a strike outside the domain — nothing is drawn off-plot", () => {
    expect(
      payoffBreakpoints({
        strikes: [710, 665, 900],
        breakeven: BE,
        domain,
      }),
    ).toEqual([domain[0], 665, BE, 710, domain[1]]);
  });

  it("de-duplicates a breakeven that lands on a strike", () => {
    expect(
      payoffBreakpoints({ strikes: [710, 665], breakeven: 710, domain }),
    ).toEqual([domain[0], 665, 710, domain[1]]);
  });
});
