import { describe, expect, it } from "vitest";

import {
  BANNED,
  EXCLUDED_FILES,
  ROOTS,
  findMissingRoots,
  lintFileContents,
} from "./lint-gold-copy.mjs";

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

/**
 * The scope, tested as a thing in its own right.
 *
 * Until P6 a root that did not exist was caught and `continue`d, so this script exited
 * **0 with no output** over a scope that had evaporated — and the port plan (§7) named
 * the move that would do it: re-homing a page shell under `/macro` removes a root. These
 * tests are the load-bearing half of that fix. Without them the next re-home reintroduces
 * the same silence, because a lint that reports nothing is indistinguishable from a lint
 * that found nothing.
 */
describe("lint scope", () => {
  it("names all four roots the desk's posture surface now spans", () => {
    // Both gold roots stay: §10-B settled that the subtrees do not move, and `app/gold`
    // still holds `loading.tsx` + `replay/[date]/` after `app/gold/page.tsx` retires into
    // `/macro/gold`. The two macro roots are the desk itself.
    expect([...ROOTS].sort()).toEqual([
      "app/gold",
      "app/macro",
      "components/gold",
      "components/macro",
    ]);
    // `components/rates` is deliberately absent — plan §10-I authorises `RatesScorecard`
    // to print its own stance word inside tab 02's refusal panel, and listing that
    // directory here would fail the build over a rendering the operator approved.
    expect(ROOTS).not.toContain("components/rates");
  });

  it("exempts only the byte-pinned operator design reference", () => {
    expect([...EXCLUDED_FILES]).toEqual([
      "components/macro/designNotesReference.ts",
    ]);
  });

  it("reports every declared root as present (vitest runs from web/)", async () => {
    expect(await findMissingRoots()).toEqual([]);
  });

  it("REPORTS a missing root rather than silently skipping it", async () => {
    // The regression this exists to catch: a root that has moved must produce a name, not
    // a clean exit. `main()` turns a non-empty result into a non-zero exit.
    const missing = await findMissingRoots([
      "components/gold",
      "components/gold-moved-somewhere-else",
    ]);
    expect(missing).toEqual(["components/gold-moved-somewhere-else"]);
  });
});
