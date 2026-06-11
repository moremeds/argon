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

  it("labels the 12:00 midday anchor per session and renders 09:30/16:00 as tick marks only", () => {
    const { container } = render(
      <GexIntradayChart data={makeSessions()} ticker="SPX" />,
    );
    // Midday is the labelled anchor — one label per session.
    expect(screen.getAllByText("12:00").length).toBe(3);
    // 09:30 and 16:00 no longer carry text labels (they used to collide at
    // adjacent-session boundaries). Their tick marks still render — see the
    // <line> count check below.
    expect(screen.queryAllByText("09:30").length).toBe(0);
    expect(screen.queryAllByText("16:00").length).toBe(0);
    // Three tick marks per session × 3 sessions = 9 short axis lines at the
    // bottom edge of the chart canvas (y1 = HEIGHT - PAD.bottom = 242).
    const tickMarks = container.querySelectorAll(
      'svg line[y1="242"][y2="244"], svg line[y1="242"][y2="246"]',
    );
    expect(tickMarks.length).toBe(9);
  });

  it("renders an alternating session band for every other session", () => {
    const { container } = render(
      <GexIntradayChart data={makeSessions()} ticker="SPX" />,
    );
    // 3 sessions → exactly 1 banded session (index 1, the middle one).
    const bands = container.querySelectorAll(
      'svg rect[fill="rgba(148,163,184,0.05)"]',
    );
    expect(bands.length).toBe(1);
  });

  it("breaks every series path at session boundaries (no overnight RTH line)", () => {
    const { container } = render(
      <GexIntradayChart data={makeSessions()} ticker="SPX" />,
    );
    // Each of 4 series paths should have 3 `M` commands — one per session —
    // so the path visually starts fresh at each 09:30 ET and never connects
    // from one session's 16:00 close to the next session's 09:30 open.
    const paths = Array.from(container.querySelectorAll("svg path"));
    expect(paths.length).toBe(4);
    for (const p of paths) {
      const d = p.getAttribute("d") ?? "";
      const moveCount = (d.match(/M/g) ?? []).length;
      expect(moveCount).toBeGreaterThanOrEqual(3);
    }
  });

  it("uses stroke-linecap=round on series paths so isolated singletons render as dots", () => {
    const { container } = render(
      <GexIntradayChart data={makeSessions()} ticker="SPX" />,
    );
    const paths = Array.from(container.querySelectorAll("svg path"));
    expect(paths.length).toBe(4);
    for (const p of paths) {
      expect(p.getAttribute("stroke-linecap")).toBe("round");
    }
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
