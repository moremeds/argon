/* @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { GexIntradayChart } from "@/components/regime/gex/GexIntradayChart";
import type { GexIntradayData } from "@/lib/regime/useGexIntraday";

/** 6.5h RTH at 5-min cadence per session, 3 sessions back-to-back. */
function makeSessions(): GexIntradayData {
  const sessions = ["2026-06-08", "2026-06-09", "2026-06-10"].map((d) => ({
    et_date: d,
    points: Array.from({ length: 78 }, (_, i) => {
      const minutesFromOpen = i * 5;
      const hour = 9 + Math.floor((30 + minutesFromOpen) / 60);
      const minute = (30 + minutesFromOpen) % 60;
      const hh = String(hour).padStart(2, "0");
      const mm = String(minute).padStart(2, "0");
      // ISO timestamp in ET (-04:00) — chart converts to ET internally.
      return {
        ts: `${d}T${hh}:${mm}:00-04:00`,
        spot: 7400 + Math.sin(i / 8) * 12 + (d === "2026-06-10" ? 5 : 0),
        net_gex: -50000 + Math.cos(i / 6) * 15000,
        gex_flip: i % 6 === 0 ? 7395 + i / 6 : null,
        iv30d: 0.18 + (i / 78) * 0.01,
      };
    }),
  }));
  return {
    ticker: "SPX",
    sessions,
    as_of: sessions[sessions.length - 1].points.at(-1)!.ts,
  };
}

describe("GexIntradayChart", () => {
  it("renders empty state when sessions is empty", () => {
    render(
      <GexIntradayChart
        data={{ ticker: "SPX", sessions: [], as_of: null }}
        ticker="SPX"
      />,
    );
    expect(screen.getByText(/no intraday gex/i)).toBeTruthy();
  });

  it("renders empty state when data is null", () => {
    render(<GexIntradayChart data={null} ticker="SPX" />);
    expect(screen.getByText(/no intraday gex/i)).toBeTruthy();
  });

  it("renders 4 series paths + session dividers for multi-session data", () => {
    const { container } = render(
      <GexIntradayChart data={makeSessions()} ticker="SPX" />,
    );
    // 4 series (spot, flip, net_gex, iv) + the swatch <line> elements per
    // legend item are siblings — only the four <path> elements should be
    // present in the SVG.
    const paths = container.querySelectorAll("svg path");
    expect(paths.length).toBe(4);

    // Header shows the session count.
    expect(screen.getByText(/last 3 sessions/i)).toBeTruthy();

    // Legend swatches present.
    expect(screen.getAllByText(/SPOT/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/GEX FLIP/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/NET GEX/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/IV 30D/i).length).toBeGreaterThan(0);

    // Date labels render (MM/DD format) for each session.
    expect(screen.getAllByText("06/08").length).toBeGreaterThan(0);
    expect(screen.getAllByText("06/09").length).toBeGreaterThan(0);
    expect(screen.getAllByText("06/10").length).toBeGreaterThan(0);
  });

  it("renders RTH tick labels (09:30, 12:00, 16:00)", () => {
    render(<GexIntradayChart data={makeSessions()} ticker="SPX" />);
    expect(screen.getAllByText("09:30").length).toBeGreaterThan(0);
    expect(screen.getAllByText("12:00").length).toBeGreaterThan(0);
    expect(screen.getAllByText("16:00").length).toBeGreaterThan(0);
  });

  it("renders the thin-data fallback when only one tick is present", () => {
    const data: GexIntradayData = {
      ticker: "SPX",
      sessions: [
        {
          et_date: "2026-06-10",
          points: [
            {
              ts: "2026-06-10T09:30:00-04:00",
              spot: 7400,
              net_gex: -50000,
              gex_flip: 7395,
              iv30d: 0.18,
            },
          ],
        },
      ],
      as_of: "2026-06-10T09:30:00-04:00",
    };
    render(<GexIntradayChart data={data} ticker="SPX" />);
    expect(screen.getByText(/needs at least 2/i)).toBeTruthy();
  });
});
