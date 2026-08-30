/* @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// `app/gold/page.tsx` is gone — `/gold` 308s into the macro desk's tab 05, and the tab is
// where the three-state settle now lives. `/gold/replay/<date>` is deliberately kept
// (plan §6), so its page is still imported here unchanged.
import { GoldTab } from "@/app/macro/[tab]/goldTab";
import GoldReplayPage from "@/app/gold/replay/[date]/page";
import { api } from "@/lib/api";

/** Tab 05 rendered live: the request the operator makes by opening `/macro/gold` with no
 *  `?as_of=`. The replay branch has its own coverage below and in
 *  `tests/unit/macroReplay.test.ts`. */
const LIVE = { replay: { kind: "live" } } as const;

vi.mock("@/lib/api", () => ({
  api: { goldState: vi.fn(), goldReplay: vi.fn() },
}));

// The cockpit itself is covered by goldCompassLayout.test.tsx. Stubbed here so
// these tests are about which of the three states the page picks, nothing else.
vi.mock("@/components/gold/GoldCompassLayout", () => ({
  GoldCompassLayout: ({ replayDate }: { replayDate?: string }) => (
    <div>cockpit rendered{replayDate ? ` for ${replayDate}` : ""}</div>
  ),
}));

// Only identity matters — GoldCompassLayout is stubbed above.
const POSTURE = { obs_date: "2026-08-27" } as never;

function body() {
  return document.body.textContent ?? "";
}

describe("gold posture surfaces — three states, never two", () => {
  beforeEach(() => {
    vi.mocked(api.goldState).mockReset();
    vi.mocked(api.goldReplay).mockReset();
  });

  it("renders the cockpit when the API answers with a posture", async () => {
    vi.mocked(api.goldState).mockResolvedValueOnce(POSTURE);

    render(await GoldTab(LIVE));

    expect(screen.getByText(/cockpit rendered/)).not.toBeNull();
  });

  it("says the posture has not been computed when the API answers with no row", async () => {
    vi.mocked(api.goldState).mockResolvedValueOnce(null);

    render(await GoldTab(LIVE));

    expect(body()).toContain("posture not yet computed");
    expect(body()).toContain("the engine has not run");
    // The distinguishing half: this must not read as an outage.
    expect(body()).not.toContain("request failed:");
  });

  it("says the request failed, and names the failure, when the API errors", async () => {
    vi.mocked(api.goldState).mockRejectedValueOnce(
      new Error("API 500 for /api/gold/state: database unavailable"),
    );

    render(await GoldTab(LIVE));

    expect(body()).toContain("posture request failed");
    expect(body()).toContain("database unavailable");
    // The distinguishing half: an unreachable API must not claim the engine
    // never ran.
    expect(body()).not.toContain("not yet computed");
    expect(body()).toContain("unknown");
  });

  it("asks the OBSERVATION endpoint when a date is requested, and says so", async () => {
    // The clock, end to end. A replayed tab 05 must call `/api/gold/replay` rather than
    // `/api/gold/state`, and the banner over it must not borrow the instant family's
    // wording — this tab is not replaying what the desk knew, it is naming a market day.
    vi.mocked(api.goldReplay).mockResolvedValueOnce({
      obs_date: "2026-08-14",
      computed_at: "2026-08-14T21:00:00Z",
    } as never);

    render(await GoldTab({ replay: { kind: "replay", asOf: "2026-08-14" } }));

    expect(api.goldReplay).toHaveBeenCalledWith("2026-08-14");
    expect(api.goldState).not.toHaveBeenCalled();
    expect(screen.getByText(/cockpit rendered for 2026-08-14/)).not.toBeNull();
    const status = screen.getByTestId("macro-replay-status");
    expect(status.getAttribute("data-replay-clock")).toBe("obs_date");
    expect(status.textContent).toContain("market day 2026-08-14");
    expect(status.textContent).not.toContain("end of 2026-08-14 UTC");
  });

  it("withholds the cockpit for a market day with no row", async () => {
    // Exact-match endpoint: a day the engine never reconstructed has no answer, and
    // nothing from a neighbouring day may be drawn under its date.
    vi.mocked(api.goldReplay).mockResolvedValueOnce(null);

    render(await GoldTab({ replay: { kind: "replay", asOf: "2026-08-14" } }));

    expect(screen.queryByText(/cockpit rendered/)).toBeNull();
    expect(body()).toContain("No row for that market day");
    expect(body()).toContain("does not fall back to the day before");
  });

  it("keeps the same three states apart on the replay route", async () => {
    vi.mocked(api.goldReplay).mockResolvedValueOnce(POSTURE);
    const answered = render(
      await GoldReplayPage({ params: Promise.resolve({ date: "2026-08-14" }) }),
    );
    expect(screen.getByText(/cockpit rendered for 2026-08-14/)).not.toBeNull();
    answered.unmount();

    vi.mocked(api.goldReplay).mockResolvedValueOnce(null);
    const missing = render(
      await GoldReplayPage({ params: Promise.resolve({ date: "2026-08-14" }) }),
    );
    expect(body()).toContain("no posture row for 2026-08-14");
    expect(body()).not.toContain("request failed:");
    missing.unmount();

    vi.mocked(api.goldReplay).mockRejectedValueOnce(new Error("fetch failed"));
    render(
      await GoldReplayPage({ params: Promise.resolve({ date: "2026-08-14" }) }),
    );
    expect(body()).toContain("posture request failed");
    expect(body()).toContain("fetch failed");
    expect(body()).not.toContain("no posture row for");
  });
});
