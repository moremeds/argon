/* @vitest-environment jsdom */
// I-108 no-change proof for the components and page split in Phase 7e. The
// snapshots and expectations here were written BEFORE the split.
import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const agentRunWeeks = vi.fn();
const agentRunWeek = vi.fn();
vi.mock("@/lib/api", () => ({
  api: {
    agentRunWeeks: (...a: unknown[]) => agentRunWeeks(...a),
    agentRunWeek: (...a: unknown[]) => agentRunWeek(...a),
  },
}));
const redirect = vi.fn((to: string) => {
  throw new Error(`REDIRECT ${to}`);
});
vi.mock("next/navigation", () => ({ redirect: (to: string) => redirect(to) }));
const todayEt = vi.fn(() => "2026-09-03");
vi.mock("@/lib/flash/kinds", async (orig) => ({
  ...(await orig<typeof import("@/lib/flash/kinds")>()),
  todayEt: () => todayEt(),
}));

import FlashIndexPage from "@/app/flash/page";
import { GrgSubTabView } from "@/components/regime/GrgSubTab";
import { MacdLegend } from "@/components/stock/panels/TechnicalsPriceChart";
import type { GrgResponse } from "@/lib/regime/useGrgLive";
import grg from "@/tests/fixtures/mcp/grg.json";

describe("GrgSubTabView markup snapshot", () => {
  it("null", () => {
    const { container } = render(<GrgSubTabView data={null} />);
    expect(container.innerHTML).toMatchSnapshot();
  });
  it("prod fixture (2026-10-02)", () => {
    const { container } = render(
      <GrgSubTabView data={grg as unknown as GrgResponse} />,
    );
    expect(container.innerHTML).toMatchSnapshot();
  });
});

describe("MacdLegend markup snapshot", () => {
  it.each([
    ["none", null],
    ["bearish", { text: "bearish", color: "var(--negative)" }],
  ])("%s", (_n, signal) => {
    const { container } = render(<MacdLegend signal={signal} />);
    expect(container.innerHTML).toMatchSnapshot();
  });
});

describe("/flash doorway", () => {
  const go = async () => {
    try {
      await FlashIndexPage();
    } catch (e) {
      return (e as Error).message;
    }
    return "no redirect";
  };
  const run = (kind: string, run_day: string) => ({ kind, run_day });

  beforeEach(() => {
    agentRunWeeks.mockReset();
    agentRunWeek.mockReset();
    todayEt.mockReturnValue("2026-09-03");
  });

  it("opens the newest past day on its latest phase, skipping future days and week kinds", async () => {
    agentRunWeeks.mockResolvedValue({ weeks: [{ week_key: "2026-W36" }] });
    agentRunWeek.mockResolvedValue({
      runs: [
        run("premarket", "2026-09-02"),
        run("close", "2026-09-02"),
        run("premarket", "2026-09-03"),
        run("premarket", "2026-09-04"),
        run("weekly", "2026-09-03"),
      ],
    });
    expect(await go()).toBe(
      "REDIRECT /flash/2026-W36/2026-09-03?phase=premarket",
    );
  });

  it("opens on close, not premarket, once the day's close is recorded", async () => {
    todayEt.mockReturnValue("2026-09-02");
    agentRunWeeks.mockResolvedValue({ weeks: [{ week_key: "2026-W36" }] });
    agentRunWeek.mockResolvedValue({
      runs: [run("close", "2026-09-02"), run("premarket", "2026-09-02")],
    });
    expect(await go()).toBe(
      "REDIRECT /flash/2026-W36/2026-09-02?phase=close",
    );
  });

  it("falls back to the last weekday when the week has no daily run", async () => {
    todayEt.mockReturnValue("2026-09-06"); // a Sunday
    agentRunWeeks.mockResolvedValue({ weeks: [{ week_key: "2026-W36" }] });
    agentRunWeek.mockResolvedValue({ runs: [] });
    expect(await go()).toBe(
      "REDIRECT /flash/2026-W36/2026-09-04?phase=premarket",
    );
  });

  it("falls back when there is no week at all", async () => {
    agentRunWeeks.mockResolvedValue({ weeks: [] });
    expect(await go()).toBe(
      "REDIRECT /flash/2026-W36/2026-09-03?phase=premarket",
    );
  });

  it("sends an unreachable API to the current week", async () => {
    agentRunWeeks.mockRejectedValue(new Error("down"));
    expect(await go()).toBe("REDIRECT /flash/2026-W36");
  });
});
