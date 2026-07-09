import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { LiveBadge } from "@/components/stock/panels/LiveBadge";

describe("LiveBadge", () => {
  it("shows LIVE + source when fresh", () => {
    const { getByText } = render(
      <LiveBadge
        captured_at={new Date().toISOString()}
        source="xenon_ws"
        maxAgeSec={900}
      />,
    );
    expect(getByText(/LIVE/)).toBeTruthy();
    expect(getByText(/xenon_ws/)).toBeTruthy();
  });
  it("shows EOD when stale/absent", () => {
    const { getByText } = render(
      <LiveBadge captured_at={null} source={null} maxAgeSec={900} />,
    );
    expect(getByText(/EOD/)).toBeTruthy();
  });
  it("shows EOD when the capture is older than maxAgeSec", () => {
    const old = new Date(Date.now() - 3600_000).toISOString();
    const { getByText } = render(
      <LiveBadge captured_at={old} source="xenon_ws" maxAgeSec={900} />,
    );
    expect(getByText(/EOD/)).toBeTruthy();
  });
});
