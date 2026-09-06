import { describe, expect, it } from "vitest";

import { SUPPORTED_SCHEMA_VERSIONS, asBriefView } from "@/components/flash/view";

function run(schema_version: number, view: unknown) {
  return {
    schema_version,
    view,
    run_day: "2026-09-04",
    headline: "h",
    outcome: "completed",
    tenant: "option-wizard",
  } as never;
}

describe("asBriefView", () => {
  it("understands both the prose-target and the typed-target shapes", () => {
    expect([...SUPPORTED_SCHEMA_VERSIONS].sort()).toEqual([1, 2]);
  });

  it("renders a v1 document, because argon deploys before helium", () => {
    const view = asBriefView(
      run(1, {
        date: "2026-09-04",
        candidates: [
          {
            id: "a",
            ticker: "SPY",
            strategy: "s",
            dte: 1,
            legs: [],
            pricing: { kind: "unpriced", reason: "r" },
            target: "grinds toward 748",
          },
        ],
      }),
    );
    expect(view).not.toBeNull();
    expect(view!.candidates![0]!.target).toBe("grinds toward 748");
  });

  it("renders a v2 document with a typed target", () => {
    const view = asBriefView(
      run(2, {
        date: "2026-09-04",
        candidates: [
          {
            id: "a",
            ticker: "SPY",
            strategy: "s",
            dte: 1,
            legs: [],
            pricing: { kind: "unpriced", reason: "r" },
            target: { level: 748, side: "below" },
            thesis: "grinds toward 748",
          },
        ],
      }),
    );
    expect(view!.candidates![0]!.target).toEqual({ level: 748, side: "below" });
    expect(view!.candidates![0]!.thesis).toBe("grinds toward 748");
  });

  it("still returns null for a version this build has never heard of", () => {
    expect(asBriefView(run(3, { date: "2026-09-04" }))).toBeNull();
  });
});
