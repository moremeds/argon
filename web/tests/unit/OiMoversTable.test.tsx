import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { OiMoversTable } from "@/components/stock/panels/OiMoversTable";

const TODAY = new Date("2026-05-13T00:00:00Z");

// Side-volume fields (ask_volume / bid_volume / mid_volume / no_side_volume)
// come from option_contract_snapshots via the LEFT JOIN in
// Repository.fetch_oi_change_top — they identify the AGGRESSOR who crossed
// the spread.
const ROWS = [
  {
    option_symbol: "GOOGL260612P00170000",
    volume: 5_000,
    avg_price: "2.40",
    oi_diff_plain: 3_200,
    ask_volume: 4_000,
    bid_volume: 600,
    mid_volume: 400,
    no_side_volume: 0,
  },
  {
    option_symbol: "GOOGL260515C00180000",
    volume: 12_000,
    avg_price: "1.20",
    oi_diff_plain: 11_000,
    ask_volume: 9_000,
    bid_volume: 800,
    mid_volume: 200,
    no_side_volume: 0,
  },
];

describe("OiMoversTable", () => {
  it("decodes OCC symbols into TYPE / EXPIRY / STRIKE columns", () => {
    render(<OiMoversTable rows={ROWS as never} spot={180} today={TODAY} />);
    expect(screen.getByText("P")).toBeTruthy();
    expect(screen.getByText("C")).toBeTruthy();
    expect(screen.getByText("2026-06-12")).toBeTruthy();
    expect(screen.getByText("2026-05-15")).toBeTruthy();
    expect(screen.getByText("$170.00")).toBeTruthy();
  });

  it("flags 0DTE on a same-day expiry", () => {
    const row = {
      option_symbol: "GOOGL260513C00180000",
      volume: 100,
      avg_price: "0.10",
      oi_diff_plain: 50,
      ask_volume: 0,
      bid_volume: 0,
      mid_volume: 0,
      no_side_volume: 0,
    };
    render(<OiMoversTable rows={[row] as never} spot={180} today={TODAY} />);
    expect(screen.getByText("0DTE LOTTO")).toBeTruthy();
  });

  it("classifies +ΔOI ask-dominant call as BUY CALL", () => {
    // 9000/(9000+800+200+0) = 90.0% ask → BUY CALL (operator lifted offer)
    render(<OiMoversTable rows={ROWS as never} spot={180} today={TODAY} />);
    expect(screen.getByText("BUY CALL")).toBeTruthy();
  });

  it("classifies +ΔOI ask-dominant put as BUY PUT", () => {
    // ROWS[0]: ask=4000/(4000+600+400+0) = 80% ask, +ΔOI, type P → BUY PUT
    render(<OiMoversTable rows={ROWS as never} spot={180} today={TODAY} />);
    expect(screen.getByText("BUY PUT")).toBeTruthy();
  });

  it("classifies +ΔOI bid-dominant call as SELL CALL", () => {
    const row = {
      option_symbol: "GOOGL260612C00200000",
      volume: 1_000,
      avg_price: "1.00",
      oi_diff_plain: 800,
      ask_volume: 100,
      bid_volume: 900,
      mid_volume: 0,
      no_side_volume: 0,
    };
    render(<OiMoversTable rows={[row] as never} spot={180} today={TODAY} />);
    expect(screen.getByText("SELL CALL")).toBeTruthy();
  });

  it("classifies −ΔOI ask-dominant as CLOSE SHORT", () => {
    const row = {
      option_symbol: "GOOGL260612C00200000",
      volume: 1_000,
      avg_price: "1.00",
      oi_diff_plain: -800,
      ask_volume: 900,
      bid_volume: 100,
      mid_volume: 0,
      no_side_volume: 0,
    };
    render(<OiMoversTable rows={[row] as never} spot={180} today={TODAY} />);
    expect(screen.getByText("CLOSE SHORT")).toBeTruthy();
  });

  it("falls back to MIXED when neither side breaches 60% dominance", () => {
    const row = {
      option_symbol: "GOOGL260612C00200000",
      volume: 1_000,
      avg_price: "1.00",
      oi_diff_plain: 500,
      ask_volume: 500,
      bid_volume: 500,
      mid_volume: 0,
      no_side_volume: 0,
    };
    render(<OiMoversTable rows={[row] as never} spot={180} today={TODAY} />);
    expect(screen.getByText("MIXED")).toBeTruthy();
  });

  it("falls back to MIXED when the aggressor denominator is zero", () => {
    const row = {
      option_symbol: "GOOGL260612C00180000",
      volume: 10,
      avg_price: "0.10",
      oi_diff_plain: 1,
      ask_volume: 0,
      bid_volume: 0,
      mid_volume: 0,
      no_side_volume: 0,
    };
    render(<OiMoversTable rows={[row] as never} spot={180} today={TODAY} />);
    expect(screen.getByText("MIXED")).toBeTruthy();
  });

  it("renders an alert-count badge when alertIndex matches the contract", () => {
    const alertIndex = new Map<string, number>([["GOOGL260515C00180000", 3]]);
    render(
      <OiMoversTable
        rows={ROWS as never}
        spot={180}
        today={TODAY}
        alertIndex={alertIndex}
      />,
    );
    expect(screen.getByText("[3 alerts]")).toBeTruthy();
  });
});
