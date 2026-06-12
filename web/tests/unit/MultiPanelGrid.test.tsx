import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  MultiPanelGrid,
  type PanelSpec,
} from "@/components/regime/MultiPanelGrid";

type Row = { a: number | null; b: number | null };

const panels: PanelSpec<Row>[] = [
  { key: "a", label: "ALPHA", get: (r) => r.a },
  { key: "b", label: "BETA", get: (r) => r.b },
];

const rows: Row[] = [
  { a: 1, b: 10 },
  { a: 2, b: null },
  { a: 3, b: 12 },
  { a: 4, b: 13 },
];

describe("MultiPanelGrid", () => {
  it("renders one mini chart per panel with latest value", () => {
    render(
      <MultiPanelGrid
        title="INTRADAY — TEST"
        panels={panels}
        rows={rows}
        dividers={[2]}
        testId="grid-test"
      />,
    );
    expect(screen.getByTestId("grid-test")).toBeTruthy();
    expect(screen.getByText("ALPHA")).toBeTruthy();
    expect(screen.getByText("BETA")).toBeTruthy();
    expect(screen.getByText("4.00")).toBeTruthy(); // latest of series a
    expect(screen.getByText("13.00")).toBeTruthy(); // latest non-null of b
  });

  it("renders empty state when no rows", () => {
    render(
      <MultiPanelGrid
        title="DAILY — TEST"
        panels={panels}
        rows={[]}
        dividers={[]}
        testId="grid-empty"
      />,
    );
    expect(screen.getByTestId("grid-empty-empty")).toBeTruthy();
  });
});
