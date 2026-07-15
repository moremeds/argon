import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { computeChanlunFull, macdHist, type ChanlunBar } from "@/lib/chanlun";
import { AAPL_DAILY_2Y } from "../unit/fixtures/aaplDaily2y";

const OUT = resolve(__dirname, "fixtures/chanlunGoldenAapl.json");

const bars: ChanlunBar[] = AAPL_DAILY_2Y.map((b) => ({
  time: b.as_of,
  high: b.high,
  low: b.low,
  close: b.close,
}));

// Deterministic serializer: sort object keys alphabetically so the file is
// byte-stable across runs (JSON.stringify drops `undefined` keys, so absent
// optional fields like level/resonant are omitted, not nulled).
function stable(value: unknown): string {
  return JSON.stringify(
    value,
    (_k, v) =>
      v && typeof v === "object" && !Array.isArray(v)
        ? Object.fromEntries(
            Object.keys(v)
              .sort()
              .map((k) => [k, (v as Record<string, unknown>)[k]]),
          )
        : v,
    2,
  );
}

describe("chanlun golden fixture", () => {
  const full = computeChanlunFull(bars);
  const golden = {
    bars,
    vertices: full.vertices,
    zhongshus: full.zhongshus,
    points: full.points,
    divergences: full.divergences,
    segVertices: full.segVertices,
    segZhongshus: full.segZhongshus,
    segPoints: full.segPoints,
    macdHist: macdHist(bars.map((b) => b.close)),
  };
  const serialized = stable(golden) + "\n";

  it("writes then stays byte-stable (never delete the committed file to force a rewrite)", () => {
    if (!existsSync(OUT)) {
      mkdirSync(dirname(OUT), { recursive: true });
      writeFileSync(OUT, serialized);
    }
    // Non-vacuity: the fixture must contain real structure, not empty arrays.
    expect(golden.vertices.length).toBeGreaterThan(0);
    expect(golden.points.length).toBeGreaterThan(0);
    expect(golden.divergences.length).toBeGreaterThan(0);
    expect(golden.segVertices.length).toBeGreaterThan(0);
    expect(golden.macdHist.length).toBe(bars.length);
    // Byte-stability: the committed file must equal a fresh serialization.
    expect(readFileSync(OUT, "utf8")).toBe(serialized);
  });
});
