/* @vitest-environment jsdom */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { VcgStressHistoryTable } from "@/components/regime/vcg/VcgStressHistoryTable";
import type { components } from "@/lib/types";

type Row = components["schemas"]["VcgStressHistoryEntry"];

const ROWS: Row[] = [
  {
    date: "2024-06-10",
    interpretation: "EDR",
    score: -1.2,
    vcg_adj: -1.2,
    pi_panic: 0,
    sign_ok: true,
    vix: 18.5,
    vvix: 95.0,
    vix_percentile_rank: 0.42,
    vvix_percentile_rank: 0.38,
  },
  {
    date: "2024-03-01",
    interpretation: "RISK_OFF",
    score: -1.85,
    vcg_adj: -1.85,
    pi_panic: 0.5,
    sign_ok: true,
    vix: 28.4,
    vvix: 105.2,
    vix_percentile_rank: 0.71,
    vvix_percentile_rank: 0.65,
  },
  {
    date: "2024-01-15",
    interpretation: "PANIC",
    score: -2.4,
    vcg_adj: -2.4,
    pi_panic: 1.2,
    sign_ok: true,
    vix: 80.86,
    vvix: 110.15,
    vix_percentile_rank: 0.992,
    vvix_percentile_rank: 0.985,
  },
];

describe("VcgStressHistoryTable", () => {
  it("renders one row per stress-state day with interpretation pills", () => {
    const { container } = render(<VcgStressHistoryTable rows={ROWS} />);
    const tbody = container.querySelector("tbody");
    expect(tbody?.querySelectorAll("tr").length).toBe(3);
    expect(
      container.querySelector('[data-testid="vcg-stress-row-2024-01-15"]'),
    ).not.toBeNull();
    expect(
      container.querySelector('[data-testid="vcg-stress-row-2024-06-10"]'),
    ).not.toBeNull();
    // RISK_OFF gets the hyphenated display label
    expect(screen.queryByText("RISK-OFF")).not.toBeNull();
  });

  it("flags PANIC rows whose VIX & VVIX percentile ranks both clear 0.95 with V2-OVERRIDE", () => {
    const { container } = render(<VcgStressHistoryTable rows={ROWS} />);
    const overrides = container.querySelectorAll(
      '[title*="v2 absolute-vol-stress override"]',
    );
    // Only the 2024-01-15 PANIC row has both percentile ranks ≥ 0.95.
    expect(overrides.length).toBe(1);
    const panicRow = container.querySelector(
      '[data-testid="vcg-stress-row-2024-01-15"]',
    );
    expect(
      panicRow?.querySelector('[title*="v2 absolute-vol-stress override"]'),
    ).not.toBeNull();
  });

  it("toggles sort order on header click", () => {
    const { container } = render(<VcgStressHistoryTable rows={ROWS} />);
    // Initial sort: date desc → most-recent first.
    const firstRow = container.querySelector("tbody tr");
    expect(firstRow?.getAttribute("data-testid")).toBe(
      "vcg-stress-row-2024-06-10",
    );
    // Click Date header → flip to asc → oldest first.
    const dateHeader = container.querySelector("thead th") as HTMLElement;
    fireEvent.click(dateHeader);
    const newFirst = container.querySelector("tbody tr");
    expect(newFirst?.getAttribute("data-testid")).toBe(
      "vcg-stress-row-2024-01-15",
    );
  });

  it("renders the empty-state row when rows is empty", () => {
    render(<VcgStressHistoryTable rows={[]} />);
    expect(
      screen.queryByText(/No stress-state days in the current backtest run\./),
    ).not.toBeNull();
  });

  it("renders '—' for null percentile ranks", () => {
    const sparse: Row[] = [
      {
        date: "2010-05-06",
        interpretation: "PANIC",
        score: -3.1,
        vcg_adj: -3.1,
        pi_panic: 1.5,
        sign_ok: true,
        vix: 40.0,
        vvix: 130.0,
        vix_percentile_rank: null,
        vvix_percentile_rank: null,
      },
    ];
    const { container } = render(<VcgStressHistoryTable rows={sparse} />);
    const row = container.querySelector(
      '[data-testid="vcg-stress-row-2010-05-06"]',
    );
    // The two percentile-rank columns render em-dashes when null
    const dashes = row?.querySelectorAll("td")[7]?.textContent;
    expect(dashes).toBe("—");
  });
});
