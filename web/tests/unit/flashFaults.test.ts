import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { faultList, viewTickers } from "@/components/flash/view";
import type { BriefView } from "@/components/flash/view";

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

/**
 * The same lesson one field over: helium's document is nullable everywhere the
 * interface says it is not. The real close run of 2026-09-03 ships two
 * `riskList` entries whose `title` is null, and the first draft of this
 * collector called `.split()` on them and took the page down.
 */
describe("viewTickers", () => {
  it("survives null titles and tickers in a real-shaped view", () => {
    const view = {
      date: "2026-09-03",
      tape: [
        { label: "SPY", value: "772.33" },
        { label: "DXY", value: "97" },
      ],
      riskList: [
        { title: null as unknown as string, body: "" },
        { title: null as unknown as string, body: "" },
      ],
      status: [{ title: "QQQ-2026-09-03-1", state: "不变", body: "" }],
    } satisfies Partial<BriefView> as BriefView;

    const tickers = viewTickers(view);
    expect(tickers.has("SPY")).toBe(true);
    // Taken from the id's leading symbol, not from the whole id.
    expect(tickers.has("QQQ")).toBe(true);
    // On the static list even though this view never structured it.
    expect(tickers.has("NVDA")).toBe(true);
    expect(tickers.has("")).toBe(false);
  });
});
