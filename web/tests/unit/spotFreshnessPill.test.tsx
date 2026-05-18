/* @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SpotFreshnessPill } from "@/components/regime/GexSubTab";

const NOW_MS = Date.parse("2026-05-17T13:30:00Z");

describe("SpotFreshnessPill", () => {
  it("renders nothing when tapeTime is null", () => {
    const { container } = render(
      <SpotFreshnessPill tapeTime={null} nowMs={NOW_MS} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing when tapeTime is invalid ISO", () => {
    const { container } = render(
      <SpotFreshnessPill tapeTime="not-a-date" nowMs={NOW_MS} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("shows LIVE when tape is ≤ 2 minutes old", () => {
    render(
      <SpotFreshnessPill tapeTime="2026-05-17T13:28:30Z" nowMs={NOW_MS} />,
    );
    const pill = screen.getByTestId("spot-freshness-pill");
    expect(pill.textContent).toBe("LIVE");
  });

  it("shows Xm ago in warning color for 3-15 minutes old", () => {
    render(
      <SpotFreshnessPill tapeTime="2026-05-17T13:18:00Z" nowMs={NOW_MS} />,
    );
    const pill = screen.getByTestId("spot-freshness-pill");
    expect(pill.textContent).toBe("12m ago");
    expect(pill.style.color).toContain("--warning");
  });

  it("shows Xm ago in muted color for 16-59 minutes old", () => {
    render(
      <SpotFreshnessPill tapeTime="2026-05-17T13:00:00Z" nowMs={NOW_MS} />,
    );
    const pill = screen.getByTestId("spot-freshness-pill");
    expect(pill.textContent).toBe("30m ago");
    expect(pill.style.color).toContain("--text-secondary");
  });

  it("shows Xh ago when over an hour old", () => {
    // 5 hours 30 min ago → "5h ago"
    render(
      <SpotFreshnessPill tapeTime="2026-05-17T08:00:00Z" nowMs={NOW_MS} />,
    );
    const pill = screen.getByTestId("spot-freshness-pill");
    expect(pill.textContent).toBe("5h ago");
  });

  it("shows Xd ago when over a day old", () => {
    // 2 days ago
    render(
      <SpotFreshnessPill tapeTime="2026-05-15T13:30:00Z" nowMs={NOW_MS} />,
    );
    const pill = screen.getByTestId("spot-freshness-pill");
    expect(pill.textContent).toBe("2d ago");
  });
});
