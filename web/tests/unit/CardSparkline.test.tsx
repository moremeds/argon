/* @vitest-environment jsdom */
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import CardSparkline from "@/components/regime/primitives/CardSparkline";

describe("CardSparkline", () => {
  it("renders an svg path for a finite series", () => {
    const { container } = render(
      <CardSparkline values={[1, 2, 3, 2.5]} label="test series" />,
    );
    const path = container.querySelector("svg path");
    expect(path).not.toBeNull();
    expect(path!.getAttribute("d")).toMatch(/^M/);
  });

  it("breaks the path at null gaps instead of interpolating", () => {
    const { container } = render(
      <CardSparkline values={[1, 2, null, 4, 5]} label="gappy series" />,
    );
    const d = container.querySelector("svg path")!.getAttribute("d")!;
    // Two sub-paths → two M commands.
    expect(d.match(/M/g)?.length).toBe(2);
  });

  it("centers a constant series instead of pinning it to the floor", () => {
    const { container } = render(
      <CardSparkline values={[5, 5, 5]} label="flat series" />,
    );
    const d = container.querySelector("svg path")!.getAttribute("d")!;
    // All y coordinates sit at mid-height (H/2 = 15), not the floor (28).
    const ys = [...d.matchAll(/[ML][\d.]+,([\d.]+)/g)].map((m) =>
      parseFloat(m[1]),
    );
    expect(ys.length).toBeGreaterThan(0);
    for (const y of ys) expect(y).toBe(15);
  });

  it("renders nothing with fewer than 2 finite points", () => {
    const { container } = render(
      <CardSparkline values={[null, 7, null]} label="sparse" />,
    );
    expect(container.querySelector("svg")).toBeNull();
  });

  it("renders nothing for an empty series", () => {
    const { container } = render(<CardSparkline values={[]} label="empty" />);
    expect(container.querySelector("svg")).toBeNull();
  });
});
