import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ExposureTile } from "@/components/stock/panels/greeks/ExposureTile";

describe("ExposureTile", () => {
  it("renders label, value, and optional sub-line", () => {
    const { getByText } = render(
      <ExposureTile label="Net Vanna" value="+$1.3M" sub="Long" />,
    );
    expect(getByText("Net Vanna")).toBeTruthy();
    expect(getByText("+$1.3M")).toBeTruthy();
    expect(getByText("Long")).toBeTruthy();
  });

  it("accepts a tone override for the value color", () => {
    const { getByText } = render(
      <ExposureTile label="x" value="-$15.5T" tone="negative" />,
    );
    const v = getByText("-$15.5T");
    expect(v.getAttribute("style") || "").toContain("var(--negative)");
  });
});
