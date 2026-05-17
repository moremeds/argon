import { describe, expect, it } from "vitest";

import {
  BANNED_POSTURE_LANGUAGE,
  findBannedSubstrings,
} from "@/lib/copy-rules";

describe("findBannedSubstrings", () => {
  it('flags "buy" as banned in v1 posture copy', () => {
    expect(findBannedSubstrings("Recommendation: buy GLD")).toContain("buy");
  });

  it('flags "position size"', () => {
    expect(findBannedSubstrings("Increase position size by 5%")).toContain(
      "position size",
    );
  });

  it("allows posture vocabulary", () => {
    expect(
      findBannedSubstrings(
        "Structural bid intact. Cyclical posture suspended.",
      ),
    ).toEqual([]);
  });

  it("does not flag word fragments (buyback != buy)", () => {
    expect(findBannedSubstrings("ETF buyback program")).not.toContain("buy");
  });

  it("flags bilingual CJK terms", () => {
    expect(findBannedSubstrings("建议今日信号触发做多")).toContain("做多");
    expect(findBannedSubstrings("建议今日信号触发做多")).toContain("今日信号");
  });

  it("flags model and backtest claims", () => {
    expect(findBannedSubstrings("SHAP waterfall shows F5 dominant")).toContain(
      "shap",
    );
    expect(findBannedSubstrings("Equity curve recovered")).toContain(
      "equity curve",
    );
  });

  it("lists banned strings", () => {
    expect(BANNED_POSTURE_LANGUAGE).toContain("buy");
    expect(BANNED_POSTURE_LANGUAGE).toContain("sell");
    expect(BANNED_POSTURE_LANGUAGE).toContain("做多");
  });
});
