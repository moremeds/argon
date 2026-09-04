import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { faultList } from "@/components/flash/view";

const HERE = dirname(fileURLToPath(import.meta.url));
const intraday = JSON.parse(
  readFileSync(
    resolve(HERE, "../../../tests/fixtures/flash/2026-09-03-intraday.json"),
    "utf8",
  ),
) as { view: { degradation?: unknown } };

/**
 * helium's BriefView emits `degradation` as ONE joined sentence; the mock
 * guessed an array and the intraday/close pages crashed on `.map` against
 * the real 2026-09-03 rows. The renderer must accept both and never throw.
 */
describe("faultList", () => {
  it("wraps helium's real single-sentence degradation", () => {
    expect(typeof intraday.view.degradation).toBe("string");
    expect(faultList(intraday.view.degradation)).toEqual([
      "Data degraded: provider provider-deepseek-dsh unavailable (no built lib/provider.js)",
    ]);
  });
  it("passes arrays through and drops non-strings", () => {
    expect(faultList(["a", 1, "b"])).toEqual(["a", "b"]);
  });
  it("is empty for missing, empty, or odd values", () => {
    expect(faultList(undefined)).toEqual([]);
    expect(faultList("")).toEqual([]);
    expect(faultList({ x: 1 })).toEqual([]);
  });
});
