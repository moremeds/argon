import { describe, expect, it } from "vitest";

import {
  SUPPORTED_SCHEMA_VERSIONS,
  asBriefView,
} from "@/components/flash/view";
import CLOSE from "../fixtures/heliumBriefViewV3Close.json";
import V2 from "../fixtures/heliumBriefViewV2.json";
import WEEKLY from "../fixtures/heliumBriefViewV3Weekly.json";

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
  it("understands the prose-target, typed-target and review shapes", () => {
    expect([...SUPPORTED_SCHEMA_VERSIONS].sort()).toEqual([1, 2, 3]);
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

  it("renders a v3 document, review blocks and all", () => {
    const view = asBriefView(run(3, WEEKLY));
    expect(view).not.toBeNull();
    expect(view!.focus!.rows[0]!.ticker).toBe("ADBE");
    expect(view!.themes![0]!.id).toBe("el-nino-ag-2026");
    expect(view!.rotation!.rows.length).toBeGreaterThan(0);
    expect(view!.footer!.coverage!.length).toBeGreaterThan(0);
    expect(view!.faults).toEqual([
      "下周展望 restates the level 14.32, which section 3 already printed",
    ]);
  });

  it("keeps the v3 close row's one-thing block, checks and all", () => {
    const view = asBriefView(run(3, CLOSE));
    expect(view!.oneThing!.title).toBe("The one thing");
    expect(view!.checks).toHaveLength(3);
    expect(view!.changeMyMind!.series).toBe("BAMLH0A0HYM2");
    expect(view!.everythingElse).toHaveLength(3);
  });

  it("does NOT touch the v2 document it already rendered", () => {
    // Every identity field is already in the document, so the adapter is a
    // pass-through: v3 support may not put a single new key on a v2 page.
    const view = asBriefView(run(2, V2));
    expect(view).toEqual(V2);
  });

  it("still returns null for a version this build has never heard of", () => {
    expect(asBriefView(run(4, { date: "2026-09-04" }))).toBeNull();
  });
});
