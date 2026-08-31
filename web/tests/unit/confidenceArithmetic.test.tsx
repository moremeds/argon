import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ConfidenceArithmetic } from "@/components/macro/ConfidenceArithmetic";
import type { MacroConfidenceReason } from "@/components/macro/types";

/**
 * The shared confidence strip, lifted in P5 from `rates/sections/StateSection.tsx`.
 *
 * `tests/unit/rates/StateSection.test.tsx` already holds this behaviour through the rates
 * page and keeps doing so — that file is the proof the lift did not change what the rates
 * desk renders. These tests hold it at the component, where all four macro domains now
 * reach it, and pin the two properties the lift must not lose.
 */

function reason(over: Partial<MacroConfidenceReason>): MacroConfidenceReason {
  return {
    term: "completeness",
    value: "1",
    detail: "3/3 load-bearing inputs present",
    kind: "multiplicand",
    ...over,
  } as MacroConfidenceReason;
}

describe("ConfidenceArithmetic", () => {
  it("sorts by kind alone, never by term name", () => {
    // §4.1 of the port plan: `market_path_is_a_shadow` shipped with `value=0` and the
    // dataclass default `kind="multiplicand"`, so the live page printed
    // "market path is a shadow ×0.00" beside a confidence of 0.850 — a term that is not in
    // the product at all, rendered as the thing that destroyed it. A filter that knew that
    // term by string would have passed straight through the bug it exists to catch, so the
    // component must decide on `kind` and the test must prove it does: the same term name,
    // the same value, two kinds, two lanes.
    const shape = { term: "market_path_is_a_shadow", value: "0", detail: "no market path" };

    const asMultiplicand = render(
      <ConfidenceArithmetic reasons={[reason({ ...shape, kind: "multiplicand" })]} />,
    );
    expect(
      asMultiplicand.getByTestId("macro-confidence-arithmetic").textContent,
    ).toMatch(/reduced by/i);
    asMultiplicand.unmount();

    const asInformational = render(
      <ConfidenceArithmetic reasons={[reason({ ...shape, kind: "informational" })]} />,
    );
    const strip = asInformational.getByTestId("macro-confidence-arithmetic");
    expect(strip.textContent).toMatch(/nothing reduced it/i);
    // Still shown — it is the one genuinely informative line — just not as a drag.
    expect(strip.textContent).toMatch(/market path is a shadow/i);
  });

  it("reads a neutral value correctly for each kind", () => {
    // A neutral value LOOKS different per term: 1.00 is neutral for a multiplicand and
    // TOTAL for a penalty. Teaching the wrong reading of its own numbers is what the strip
    // replaced a six-row sub-card to stop.
    render(
      <ConfidenceArithmetic
        reasons={[
          reason({ term: "completeness", value: "1", kind: "multiplicand" }),
          reason({ term: "revision_penalty", value: "0", kind: "penalty" }),
        ]}
      />,
    );
    expect(
      screen.getByTestId("macro-confidence-arithmetic").textContent,
    ).toMatch(/nothing reduced it/i);
  });

  it("names both a biting penalty and a multiplicand below one", () => {
    render(
      <ConfidenceArithmetic
        reasons={[
          reason({ term: "completeness", value: "0.67", kind: "multiplicand" }),
          reason({
            term: "contradiction_penalty",
            value: "0.20",
            detail: "2 rule(s) fired",
            kind: "penalty",
          }),
        ]}
      />,
    );
    const text = screen.getByTestId("macro-confidence-arithmetic").textContent ?? "";
    expect(text).toMatch(/reduced by/i);
    // A penalty reads as a subtraction, a multiplicand as a factor. Rendering both the
    // same way is the misreading, not the length.
    expect(text).toContain("−20%");
    expect(text).toContain("×0.67");
  });

  it("never re-folds the confidence number itself", () => {
    // The confidence is the engine's, printed by the caller. A product recomputed here
    // would be a second arithmetic on screen that could disagree with the stored one — and
    // the desk's posture is that a stored answer is replayed, never recomputed at read
    // time. So the strip prints terms and no total.
    render(
      <ConfidenceArithmetic
        reasons={[
          reason({ term: "completeness", value: "0.5", kind: "multiplicand" }),
          reason({ term: "quality", value: "0.5", kind: "multiplicand" }),
        ]}
      />,
    );
    const text = screen.getByTestId("macro-confidence-arithmetic").textContent ?? "";
    expect(text).toContain("×0.50");
    // 0.5 × 0.5 = 0.25. If that ever appears, someone folded the product.
    expect(text).not.toContain("0.25");
    expect(text).not.toMatch(/total|product|=/i);
  });

  it("renders nothing at all when a state published no terms", () => {
    const { container } = render(<ConfidenceArithmetic reasons={[]} />);
    expect(container.innerHTML).toBe("");
  });

  it("takes the caller's testid, so the rates desk keeps its own contract", () => {
    render(
      <ConfidenceArithmetic
        reasons={[reason({})]}
        testId="rates-confidence-strip"
      />,
    );
    expect(screen.getByTestId("rates-confidence-strip")).toBeTruthy();
  });
});
