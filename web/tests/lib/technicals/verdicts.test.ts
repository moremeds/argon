// Branch coverage for the verdict engines moved to lib/technicals/verdicts.ts.
// These are the same pure functions the panels call — the inputs are literals
// exercising each branch, plus one pass on the frozen fixtures' real detail
// fields.
import { describe, expect, it } from "vitest";
import type { TechnicalsResponse } from "@/lib/api";
import {
  alignmentBadge,
  kinematicsReading,
  macdSignalText,
  sigmoidRejectReason,
} from "@/lib/technicals/verdicts";
import aapl from "@/tests/fixtures/mcp/aapl_technicals.json";

describe("kinematicsReading", () => {
  it("returns null when any t-stat is missing", () => {
    expect(kinematicsReading(null, 2.5, 3)).toBeNull();
    expect(kinematicsReading(2.5, undefined, 3)).toBeNull();
    expect(kinematicsReading(2.5, 3, null)).toBeNull();
  });

  it("reports no reliable slope when all |t| < 2", () => {
    expect(kinematicsReading(0.5, -1.9, 1)).toBe(
      "Reading: no MA slope is statistically reliable — no trend.",
    );
    expect(kinematicsReading(-1.99, 1.99, 0)).toMatch(/no MA slope/);
  });

  it("reports disagreement when reliable slopes point both ways", () => {
    expect(kinematicsReading(2.5, -2.5, 3)).toBe(
      "Reading: slopes disagree (3/3 reliable) — no clean trend.",
    );
    expect(kinematicsReading(-2.1, 2.1, 0)).toBe(
      "Reading: slopes disagree (2/3 reliable) — no clean trend.",
    );
  });

  it("confirms an uptrend when all three reliable slopes are positive", () => {
    expect(kinematicsReading(2.1, 3, 10)).toBe(
      "Reading: all three MAs rising, statistically reliable — confirmed uptrend.",
    );
  });

  it("calls a partial agreement tentative", () => {
    expect(kinematicsReading(-2.1, -3, 1)).toBe(
      "Reading: 2/3 MAs falling, statistically reliable — tentative downtrend.",
    );
    expect(kinematicsReading(2.1, 0.5, 1.9)).toBe(
      "Reading: 1/3 MAs rising, statistically reliable — tentative uptrend.",
    );
  });

  it("passes through on the frozen AAPL detail (t ≈ 25.8/22.6/115.4, align 3)", () => {
    const detail = (aapl as unknown as TechnicalsResponse).detail as
      | {
          kinematics?: {
            sma20?: { tstat?: number | null };
            sma50?: { tstat?: number | null };
            sma200?: { tstat?: number | null };
            alignment?: number | null;
          };
          dual_macd?: {
            trend_state?: string;
            tactical_signal?: string;
            confidence?: number | null;
          };
          sigmoid?: {
            r2_sigmoid?: number | null;
            r2_linear?: number | null;
          };
        }
      | undefined;
    const kin = detail?.kinematics;
    expect(
      kinematicsReading(
        kin?.sma20?.tstat,
        kin?.sma50?.tstat,
        kin?.sma200?.tstat,
      ),
    ).toBe(
      "Reading: all three MAs rising, statistically reliable — confirmed uptrend.",
    );
    expect(alignmentBadge(kin?.alignment)).toEqual({
      label: "BULL",
      count: 3,
      text: "BULL ALIGN 3/3",
    });
    expect(macdSignalText(detail?.dual_macd)).toEqual({
      text: "BULLISH",
      key: "BULLISH",
    });
    // r2_sig 0.821 ≥ 0.80 and clears r2_lin 0.742 + 0.05 → the wrong-way clause.
    expect(
      sigmoidRejectReason(
        detail?.sigmoid?.r2_sigmoid,
        detail?.sigmoid?.r2_linear,
      ),
    ).toMatch(/bends the wrong way/);
  });
});

describe("alignmentBadge", () => {
  it("is null without an alignment value", () => {
    expect(alignmentBadge(null)).toBeNull();
    expect(alignmentBadge(undefined)).toBeNull();
  });

  it("labels bull/bear/mixed and carries the |a|/3 count", () => {
    expect(alignmentBadge(3)).toEqual({
      label: "BULL",
      count: 3,
      text: "BULL ALIGN 3/3",
    });
    expect(alignmentBadge(-2)).toEqual({
      label: "BEAR",
      count: 2,
      text: "BEAR ALIGN 2/3",
    });
    expect(alignmentBadge(0)).toEqual({
      label: "MIXED",
      count: 0,
      text: "MIXED ALIGN 0/3",
    });
    expect(alignmentBadge(1)?.label).toBe("BULL");
    expect(alignmentBadge(-1)?.label).toBe("BEAR");
  });
});

describe("macdSignalText", () => {
  it("is null without a detail or any signal", () => {
    expect(macdSignalText(undefined)).toBeNull();
    expect(macdSignalText({})).toBeNull();
    expect(macdSignalText({ tactical_signal: "NONE" })).toBeNull();
  });

  it("prefers the tactical signal, formatted with its confidence", () => {
    expect(
      macdSignalText({ tactical_signal: "DIP_BUY", confidence: 0.846 }),
    ).toEqual({ text: "DIP_BUY · conf 0.85", key: "DIP_BUY" });
    expect(
      macdSignalText({ tactical_signal: "RALLY_SELL", confidence: null }),
    ).toEqual({ text: "RALLY_SELL · conf —", key: "RALLY_SELL" });
  });

  it("falls back to the trend state when no tactical signal", () => {
    expect(macdSignalText({ trend_state: "BULLISH" })).toEqual({
      text: "BULLISH",
      key: "BULLISH",
    });
    expect(
      macdSignalText({ trend_state: "BEARISH", tactical_signal: "NONE" }),
    ).toEqual({ text: "BEARISH", key: "BEARISH" });
  });
});

describe("sigmoidRejectReason", () => {
  it("names the missing-history branch", () => {
    expect(sigmoidRejectReason(null, 0.5)).toMatch(/not enough clean history/);
    expect(sigmoidRejectReason(undefined, undefined)).toMatch(
      /not enough clean history/,
    );
  });

  it("names the absolute-fit branch below 80%", () => {
    expect(sigmoidRejectReason(0.31, 0.05)).toMatch(/too choppy/);
    expect(sigmoidRejectReason(0.79, 0)).toMatch(/79%/);
  });

  it("stays generic when r2_linear is absent", () => {
    expect(sigmoidRejectReason(0.9, null)).toMatch(
      /doesn't clear the bar over a plain trend line/,
    );
    expect(sigmoidRejectReason(0.95, undefined)).toMatch(
      /doesn't clear the bar/,
    );
  });

  it("names the beats-linear branch when the curve only matches a line", () => {
    expect(sigmoidRejectReason(0.9, 0.88)).toMatch(/straight line/);
    expect(sigmoidRejectReason(0.85, 0.81)).toMatch(/85% vs linear 81%/);
  });

  it("falls through to the wrong-way branch", () => {
    expect(sigmoidRejectReason(0.95, 0.1)).toMatch(/bends the wrong way/);
    expect(sigmoidRejectReason(0.8, 0.75)).toMatch(/bends the wrong way/);
  });
});
