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

  it("colors percentile-rank cells red when v >= 0.95 (vol-stress threshold)", () => {
    const { container } = render(<VcgStressHistoryTable rows={ROWS} />);
    // 2024-01-15 PANIC row: both percentile ranks clear 0.95 → both cells red.
    const panicRow = container.querySelector(
      '[data-testid="vcg-stress-row-2024-01-15"]',
    );
    const tds = panicRow?.querySelectorAll("td");
    const vixCell = tds?.[7] as HTMLElement | undefined;
    const vvixCell = tds?.[8] as HTMLElement | undefined;
    expect(vixCell?.style.color).toContain("var(--fault");
    expect(vvixCell?.style.color).toContain("var(--fault");
    // 2024-06-10 EDR row: both ranks well under 0.95 → text-primary (not red).
    const edrRow = container.querySelector(
      '[data-testid="vcg-stress-row-2024-06-10"]',
    );
    const edrCells = edrRow?.querySelectorAll("td");
    const edrVix = edrCells?.[7] as HTMLElement | undefined;
    expect(edrVix?.style.color).toContain("var(--text-primary)");
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

  it("renders +5d / +20d / +60d forward-return cells with sign coloring", () => {
    const rows: Row[] = [
      {
        date: "2020-03-16",
        interpretation: "PANIC",
        score: -3.2,
        vcg_adj: -3.2,
        pi_panic: 1.5,
        sign_ok: true,
        vix: 80,
        vvix: 130,
        vix_percentile_rank: 0.99,
        vvix_percentile_rank: 0.99,
        fwd_5d_pct: -8.5,
        fwd_20d_pct: 15.3,
        fwd_60d_pct: 22.1,
      },
    ];
    const { container } = render(<VcgStressHistoryTable rows={rows} />);
    const row = container.querySelector(
      '[data-testid="vcg-stress-row-2020-03-16"]',
    );
    const cells = row?.querySelectorAll("td");
    // Columns 9, 10, 11 are +5d / +20d / +60d
    expect(cells?.[9]?.textContent).toMatch(/-8\.5/);
    expect(cells?.[10]?.textContent).toMatch(/\+15\.3/);
    expect(cells?.[11]?.textContent).toMatch(/\+22\.1/);
    // Negative fwd_5d should be red; positive should be green
    expect((cells?.[9] as HTMLElement).style.color).toContain("var(--negative");
    expect((cells?.[10] as HTMLElement).style.color).toContain(
      "var(--positive",
    );
  });

  it("renders '—' for null forward-return cells (recent days)", () => {
    const rows: Row[] = [
      {
        date: "2026-05-27",
        interpretation: "RISK_OFF",
        score: -1.9,
        vcg_adj: -1.9,
        pi_panic: 0,
        sign_ok: true,
        vix: 25,
        vvix: 110,
        vix_percentile_rank: 0.7,
        vvix_percentile_rank: 0.6,
        fwd_5d_pct: 0.5,
        fwd_20d_pct: null,
        fwd_60d_pct: null,
      },
    ];
    const { container } = render(<VcgStressHistoryTable rows={rows} />);
    const row = container.querySelector(
      '[data-testid="vcg-stress-row-2026-05-27"]',
    );
    const cells = row?.querySelectorAll("td");
    expect(cells?.[10]?.textContent).toBe("—");
    expect(cells?.[11]?.textContent).toBe("—");
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
