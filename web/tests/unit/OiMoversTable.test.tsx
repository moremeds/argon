import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { OiMoversTable } from "@/components/stock/panels/OiMoversTable";

const TODAY = new Date("2026-05-13T00:00:00Z");

const ROWS = [
  {
    option_symbol: "GOOGL260612P00170000",
    volume: 5_000,
    avg_price: "2.40",
    oi_diff_plain: -3_200,
    prev_ask_volume: 1_000,
    prev_bid_volume: 3_500,
    prev_mid_volume: 500,
    prev_neutral_volume: 0,
  },
  {
    option_symbol: "GOOGL260515C00180000",
    volume: 12_000,
    avg_price: "1.20",
    oi_diff_plain: 11_000,
    prev_ask_volume: 9_000,
    prev_bid_volume: 800,
    prev_mid_volume: 200,
    prev_neutral_volume: 0,
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
      prev_ask_volume: 0,
      prev_bid_volume: 0,
      prev_mid_volume: 0,
      prev_neutral_volume: 0,
    };
    render(<OiMoversTable rows={[row] as never} spot={180} today={TODAY} />);
    expect(screen.getByText("0DTE LOTTO")).toBeTruthy();
  });

  it("computes ASK% from prev_* aggressor split", () => {
    render(<OiMoversTable rows={ROWS as never} spot={180} today={TODAY} />);
    // Second row: ask=9000 / (9000+800+200+0) = 90.0%
    expect(screen.getByText("90.0%")).toBeTruthy();
    // First row: 1000 / 5000 = 20.0%
    expect(screen.getByText("20.0%")).toBeTruthy();
  });

  it("renders em-dash when aggressor denominator is zero", () => {
    const row = {
      option_symbol: "GOOGL260612C00180000",
      volume: 10,
      avg_price: "0.10",
      oi_diff_plain: 1,
      prev_ask_volume: 0,
      prev_bid_volume: 0,
      prev_mid_volume: 0,
      prev_neutral_volume: 0,
    };
    render(<OiMoversTable rows={[row] as never} spot={180} today={TODAY} />);
    // The ASK% cell renders em-dash; at least one such cell should appear.
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });
});
