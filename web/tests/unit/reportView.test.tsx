/**
 * The report renderer walks an arbitrary jsonb payload, so its two failure
 * modes are structural rather than logical: a number printed at raw float
 * precision, and a nested object that inherits a cell instead of a row.
 * Both shipped. Both are asserted here against the real comparison shape.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ReportView } from "@/components/reports/ReportView";
import type { ReportResponse } from "@/lib/api";

function payload(value: unknown): ReportResponse {
  return {
    state: "ok",
    report: {
      report_id: 1,
      report_type: "comparison",
      report_key: "comparison:AMD-NVDA",
      title: "AMD vs NVDA comparison",
      version_no: 1,
      status: "published",
      content_hash: "deadbeef",
      manifest: { as_of: "2026-08-25", engine_version: "fundamentals-v2:77aea364" },
      published_at: "2026-08-25T08:36:00Z",
      blocks: [
        {
          ordinal: 0,
          block_kind: "comparison_table",
          title: "Research priority, ordered",
          authority: "research_priority",
          payload: value as Record<string, unknown>,
          evidence: { engine_version: "fundamentals-v2:77aea364" },
          derivation: null,
        },
      ],
    },
    delta: null,
    versions: [{ version_no: 1, status: "published", published_at: null }],
  } as unknown as ReportResponse;
}

const ROWS = {
  n: 1,
  rows: [
    {
      ticker: "CRDO",
      priority: 0.419931924774829,
      dimensions: { growth: 1.17329190411882, balance_sheet: 0.4596259642937 },
      inputs_present: 12,
    },
  ],
};

function view(value: unknown) {
  return render(
    <ReportView data={payload(value)} reportType="comparison" reportKey="AMD-NVDA" />,
  );
}

describe("ReportView payload rendering", () => {
  it("rounds a score and never shows its raw float", () => {
    view(ROWS);
    expect(screen.getByText("0.4199")).toBeTruthy();
    expect(screen.queryByText("0.419931924774829")).toBeNull();
  });

  it("leaves an integer count alone — 12 inputs is not a measurement to 4dp", () => {
    view(ROWS);
    expect(screen.getByText("12")).toBeTruthy();
    expect(screen.queryByText("12.0000")).toBeNull();
  });

  it("gives a nested structure the full row, not a third of a third", () => {
    // The regression: `dimensions` inside a grid cell rendered at a ninth of
    // the page and broke "balance_sheet" mid-word.
    const { container } = view(ROWS);
    const label = Array.from(container.querySelectorAll("dt")).find(
      (n) => n.textContent === "dimensions",
    );
    expect(label?.parentElement?.className).toContain("col-span-full");
  });

  it("keeps a scalar sharing the columns", () => {
    const { container } = view(ROWS);
    const label = Array.from(container.querySelectorAll("dt")).find(
      (n) => n.textContent === "n",
    );
    expect(label?.parentElement?.className ?? "").not.toContain("col-span-full");
  });

  it("renders a null as `na`, never as a blank that reads as zero", () => {
    view({ priority: null });
    expect(screen.getByText("na")).toBeTruthy();
  });
});
