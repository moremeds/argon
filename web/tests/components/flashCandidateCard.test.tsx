import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CandidateCard } from "@/components/flash/CandidateCard";
import type { CandidateView } from "@/components/flash/view";
import { QQQ_SPREAD } from "../fixtures/flashRun";

describe("CandidateCard", () => {
  it("renders the recorded QQQ put debit spread", () => {
    const { container } = render(<CandidateCard candidate={QQQ_SPREAD} />);
    expect(screen.getByText("QQQ")).toBeTruthy();
    // Underscores are a machine's word separator, not a reader's.
    expect(screen.getByText("put debit spread")).toBeTruthy();
    expect(container.textContent).toContain("Exp 2026-10-02");
    expect(container.textContent).toContain("29 DTE");
    expect(container.textContent).toContain("Spot 717.29");
    expect(container.textContent).toContain("Width 45.00");
    expect(screen.getByText("QQQ-2026-09-03-1")).toBeTruthy();
  });

  it("lists both legs under one header row", () => {
    render(<CandidateCard candidate={QQQ_SPREAD} />);
    const rows = screen.getAllByRole("row");
    expect(rows).toHaveLength(3);
    expect(within(rows[1]).getByText("buy")).toBeTruthy();
    expect(within(rows[1]).getByText("710.00")).toBeTruthy();
    expect(within(rows[1]).getByText("10.45")).toBeTruthy();
    expect(within(rows[2]).getByText("sell")).toBeTruthy();
    expect(within(rows[2]).getByText("665.00")).toBeTruthy();
  });

  it("prints the derived economics with a real minus sign", () => {
    render(<CandidateCard candidate={QQQ_SPREAD} />);
    expect(screen.getByText("$7.74")).toBeTruthy();
    expect(screen.getByText("+$3,726.00")).toBeTruthy();
    expect(screen.getByText("−$774.00")).toBeTruthy();
  });

  it("carries no quantity, size or account state", () => {
    const { container } = render(<CandidateCard candidate={QQQ_SPREAD} />);
    expect(container.textContent).not.toMatch(/\bqty\b|\bsize\b|\bnet liq\b/i);
  });

  it("renders entry and invalidation as level plus side", () => {
    const { container } = render(<CandidateCard candidate={QQQ_SPREAD} />);
    expect(container.textContent).toContain("710 below");
    expect(container.textContent).toContain("720 above");
  });

  it("surfaces an unchecked note when the run set one", () => {
    const unchecked: CandidateView = {
      ...QQQ_SPREAD,
      unchecked: "earnings date not verified",
    };
    render(<CandidateCard candidate={unchecked} />);
    expect(
      screen.getByText(/Unchecked: earnings date not verified/),
    ).toBeTruthy();
  });

  it("replaces the pricing row with the reason when unpriced", () => {
    const unpriced: CandidateView = {
      ...QQQ_SPREAD,
      pricing: { kind: "unpriced", reason: "no NBBO for the 665 put" },
    };
    const { container } = render(<CandidateCard candidate={unpriced} />);
    expect(screen.getByText(/no NBBO for the 665 put/)).toBeTruthy();
    expect(container.querySelector("svg")).toBeNull();
    expect(container.textContent).not.toContain("Max gain");
  });
});

describe("target and thesis", () => {
  const v2 = {
    ...QQQ_SPREAD,
    target: { level: 748, side: "below" as const },
    thesis: "QQQ fades into the September gamma shelf",
  };

  it("prints a typed target as a level", () => {
    const { container } = render(<CandidateCard candidate={v2} />);
    expect(container.textContent).toContain("748 below");
  });

  it("prints the thesis sentence", () => {
    const { container } = render(<CandidateCard candidate={v2} />);
    expect(container.textContent).toContain(
      "QQQ fades into the September gamma shelf",
    );
  });

  it("prints a v1 prose target verbatim instead of an em dash", () => {
    const v1 = { ...QQQ_SPREAD, target: "fades into the gamma shelf" };
    const { container } = render(<CandidateCard candidate={v1} />);
    expect(container.textContent).toContain("fades into the gamma shelf");
  });

  it("prints an em dash and no undefined when there is no target at all", () => {
    const { container } = render(<CandidateCard candidate={QQQ_SPREAD} />);
    expect(container.textContent).toContain("—");
    expect(container.textContent).not.toContain("undefined");
  });
});
