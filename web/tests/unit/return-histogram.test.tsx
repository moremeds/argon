import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { TechnicalsResponse } from "@/lib/api";
import {
  ReturnHistogram,
  returnBins,
} from "@/components/stock/panels/ReturnHistogram";

describe("returnBins", () => {
  it("bins returns, conserving count and computing moments", () => {
    const rets = [-0.02, -0.01, 0, 0, 0.01, 0.01, 0.02, 0.03];
    const b = returnBins(rets, 11);
    expect(b.counts.reduce((a, c) => a + c, 0)).toBe(rets.length);
    expect(b.edges.length).toBe(b.counts.length + 1);
    const mean = rets.reduce((a, c) => a + c, 0) / rets.length;
    expect(b.mean).toBeCloseTo(mean, 6);
    expect(b.sd).toBeGreaterThan(0);
  });

  it("returns empty bins for too-few points", () => {
    expect(returnBins([0.01], 11).counts.every((c) => c === 0)).toBe(true);
  });
});

describe("ReturnHistogram", () => {
  it("renders a titled distribution chart from series closes", () => {
    const series = Array.from({ length: 80 }, (_, i) => ({
      as_of: `2026-01-${(i % 28) + 1}`,
      close: 100 * (1 + 0.01 * Math.sin(i / 3)),
    }));
    const data = { series } as unknown as TechnicalsResponse;
    const { getAllByText } = render(<ReturnHistogram data={data} />);
    expect(getAllByText(/Return Distribution/i).length).toBeGreaterThan(0);
  });
});
