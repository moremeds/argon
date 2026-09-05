import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CandidateCard } from "@/components/flash/CandidateCard";
import { asBriefView } from "@/components/flash/view";
import fixture from "../fixtures/heliumBriefViewV2.json";

/**
 * The producer's own output, not a mirror of it. A hand-written fixture tests
 * that argon agrees with argon; this one fails when helium's real document
 * stops rendering, which is the only failure worth catching here.
 */
describe("helium brief-view v2", () => {
  const view = asBriefView({
    schema_version: (fixture as { schemaVersion: number }).schemaVersion,
    view: fixture,
    run_day: "2026-09-04",
    headline: "h",
    outcome: "completed",
    tenant: "option-wizard",
  } as never);

  it("is a shape this build renders", () => {
    expect(view).not.toBeNull();
    expect(view!.candidates!.length).toBeGreaterThan(0);
  });

  it("draws every candidate with no undefined and a real target", () => {
    for (const candidate of view!.candidates!) {
      const { container } = render(<CandidateCard candidate={candidate} />);
      expect(container.textContent).not.toContain("undefined");
      expect(container.textContent).not.toContain("[object Object]");
      expect(container.textContent).toContain(candidate.ticker);
    }
  });

  it("prints the first candidate's target as a number and a side", () => {
    const target = view!.candidates![0]!.target;
    expect(typeof target).toBe("object");
    const { container } = render(
      <CandidateCard candidate={view!.candidates![0]!} />,
    );
    expect(container.textContent).toContain(
      `${(target as { level: number }).level} ${(target as { side: string }).side}`,
    );
  });
});
