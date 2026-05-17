import { describe, expect, it } from "vitest";

import { BANNED, lintFileContents } from "./lint-gold-copy.mjs";

describe("lintFileContents", () => {
  it("flags every banned category", () => {
    const cases = [
      'export const X = "buy gold now";',
      'export const X = "position size 1%";',
      'export const X = "execute trade";',
      'export const X = "predicted return +0.72%";',
      'export const X = "equity curve since 2020";',
      'export const X = "今日信号: 做多";',
    ];
    for (const src of cases) {
      const v = lintFileContents("Test.tsx", src);
      expect(v.length, src).toBeGreaterThan(0);
    }
  });

  it("permits posture-language copy", () => {
    expect(
      lintFileContents("Test.tsx", 'export const X = "structural bid intact";'),
    ).toEqual([]);
    expect(
      lintFileContents(
        "Test.tsx",
        'export const X = "tail-risk awareness only";',
      ),
    ).toEqual([]);
    expect(
      lintFileContents(
        "Test.tsx",
        'export const X = "long-horizon allocation context";',
      ),
    ).toEqual([]);
  });

  it("respects // posture-lint-disable-next-line", () => {
    const src = [
      "// posture-lint-disable-next-line: Baur-Lucey academic quote",
      'const Q = "a safe haven that does not lose value when others sell";',
    ].join("\n");
    expect(lintFileContents("Cited.tsx", src)).toEqual([]);
  });

  it("exposes the banned-string list for inspection", () => {
    expect(BANNED).toContain("buy");
    expect(BANNED).toContain("predicted return");
    expect(BANNED).toContain("做多");
  });
});
