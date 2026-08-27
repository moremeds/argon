/* @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import GoldPage from "@/app/gold/page";
import GoldReplayPage from "@/app/gold/replay/[date]/page";
import { api } from "@/lib/api";

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

describe("gold posture page — three states, never two", () => {
  beforeEach(() => {
    vi.mocked(api.goldState).mockReset();
    vi.mocked(api.goldReplay).mockReset();
  });

  it("renders the cockpit when the API answers with a posture", async () => {
    vi.mocked(api.goldState).mockResolvedValueOnce(POSTURE);

    render(await GoldPage());

    expect(screen.getByText(/cockpit rendered/)).not.toBeNull();
  });

  it("says the posture has not been computed when the API answers with no row", async () => {
    vi.mocked(api.goldState).mockResolvedValueOnce(null);

    render(await GoldPage());

    expect(body()).toContain("posture not yet computed");
    expect(body()).toContain("the engine has not run");
    // The distinguishing half: this must not read as an outage.
    expect(body()).not.toContain("request failed:");
  });

  it("says the request failed, and names the failure, when the API errors", async () => {
    vi.mocked(api.goldState).mockRejectedValueOnce(
      new Error("API 500 for /api/gold/state: database unavailable"),
    );

    render(await GoldPage());

    expect(body()).toContain("posture request failed");
    expect(body()).toContain("database unavailable");
    // The distinguishing half: an unreachable API must not claim the engine
    // never ran.
    expect(body()).not.toContain("not yet computed");
    expect(body()).toContain("unknown");
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
